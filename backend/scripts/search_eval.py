"""Проверочный набор поиска (search-01): `search()` и `find_target()` на стартовом датасете.

Два набора:
- базовый — из замера техлида при выборе подхода: 30 запросов с ответом (примеры из задания,
  `docs/test-cases.md` раздел 5 и свои — другие формы слов, сокращения, «е» вместо «ё»),
  6 без ответа и 24 цели изменения. Эталон — регулярные выражения по названию;
- расширенный (`scripts/search_cases.py`) — сотни запросов и целей по группам граничных
  случаев; эталон — понятия, разобранные из названий по шаблонам датасета.

Данные: стартовый набор нового пользователя (`bootstrap_user_data`), пояс Europe/Moscow,
«сейчас» = 21.10.2026 12:00, как в `docs/test-cases.md`.

Метрики:
- поиск: hit@5 — среди не больше 5 результатов `search(limit=5)` есть подходящая запись;
  «точно» на запросах без ответа — сколько раз `search()` ответил `exact` там, где ответа нет;
  точность «точно» — все ли `exact`-результаты подходящие;
- цели: исход `find_target(statuses=[active])` — действие над верной, чужая запись (ошибка,
  которой быть не должно), «какую?» с верными кандидатами, лишний переспрос, «не нашёл».

Запуск (нужны PostgreSQL с pgvector и модель в кэше Hugging Face):
    cd backend && uv run python -m scripts.search_eval              # базовый набор
    cd backend && uv run python -m scripts.search_eval --extended   # оба набора
Данные пишутся в транзакции, которая откатывается: база не меняется.
"""

import argparse
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from schemas import RecordStatus, RecordType, SearchFilters

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=TZ)

# (запрос как в SearchRecords.query, фильтр типов, эталон). [] — ответа в данных нет.
SEARCH_SET: list[tuple[str, list[str] | None, list[str]]] = [
    ("презентация", ["task"], [r"презентац"]),  # A-10
    ("встреча с Иваном", ["meeting"], [r"иван"]),  # A-11
    ("договор", ["task"], [r"договор"]),  # A-12
    ("встреча с Марией по хакатону", ["meeting"], [r"мари", r"хакатон"]),  # 5.1
    ("смета для Максима", None, [r"смет", r"максим"]),  # 5.2
    ("созвон с Севером", ["meeting"], [r"север"]),  # 5.3
    ("демо по мобильному приложению", None, [r"демо", r"мобильн"]),  # 5.4
    ("отправить Ольге", None, [r"отправить", r"ольг"]),  # 5.5
    ("коммерческое предложение", None, [r"коммерческ"]),  # 5.7
    ("звонил Дмитрию", None, [r"позвонить", r"дмитри"]),  # 5.8
    ("смета", ["task"], [r"смет"]),  # 5.9
    ("Дмитрий бюджет", None, [r"дмитри", r"бюджет"]),  # 5.10
    ("хакатон", ["meeting"], [r"хакатон"]),  # 5.11
    ("звонок Анне", None, [r"позвонить", r"анн"]),
    ("планёрка по CRM", None, [r"планёрк", r"crm"]),
    ("техническое задание", None, [r"техническ"]),
    ("ТЗ", None, [r"техническ"]),  # сокращение
    ("созвон с Альфой", ["meeting"], [r"альф"]),
    ("акт на согласование", None, [r"\bакт\b", r"согласован"]),
    ("обратная связь по сайту", None, [r"обратн", r"сайт"]),
    ("сроки по интеграции", None, [r"срок", r"интеграц"]),
    ("мобилка", None, [r"мобильн"]),  # разговорное, 5.13
    ("Наталья", None, [r"натал"]),
    ("встреча с Ольгой по бюджету", ["meeting"], [r"ольг", r"бюджет"]),
    ("отчет", None, [r"отч[её]т"]),  # «е» вместо «ё»
    ("компания Вектор", None, [r"вектор"]),
    ("аналитика с Еленой", None, [r"елен", r"аналитик"]),
    ("подготовка к встрече с Орбитой", None, [r"орбит"]),
    ("напоминание про CRM Анне", ["reminder"], [r"анн", r"crm"]),
    ("статус задачи по сайту", None, [r"статус", r"сайт"]),
    # ответа нет
    ("созвон с юристами", None, []),  # 5.17
    ("встреча с дизайнером", None, []),
    ("купить молоко", None, []),  # 5.15
    ("отпуск", None, []),
    ("день рождения мамы", None, []),
    ("ремонт машины", None, []),
]

# (TargetRef.text, when: None | "date" | "datetime", эталон). when берётся у самой ранней
# подходящей активной записи: «date» — полночь её дня (агент передаёт день без времени так),
# «datetime» — её точное время.
TARGET_SET: list[tuple[str, str | None, list[str]]] = [
    # одна подходящая — действовать
    ("встречу с Иваном", None, [r"^встреча", r"иван"]),
    ("созвон с Вектором", None, [r"^созвон", r"вектор"]),
    ("встречу с Марией по хакатону", None, [r"^встреча", r"мари", r"хакатон"]),
    ("созвон с Пульсом", None, [r"^созвон", r"пульс"]),
    ("задачу про смету для Максима", None, [r"смет", r"максим"]),
    ("планёрку по сайту", "date", [r"планёрк", r"сайт"]),
    ("подготовиться к встрече с Альфой", "datetime", [r"^подготовиться", r"альф"]),
    ("отправить смету Ивану", None, [r"^отправить смет", r"иван"]),
    ("согласовать презентацию с Иваном", None, [r"^согласовать презентац", r"иван"]),
    ("демо по мобильному приложению", None, [r"^демо", r"мобильн"]),
    ("напоминание про бюджет Максиму", None, [r"^напомнить", r"максим", r"бюджет"]),
    # несколько — спросить «какую?»
    ("позвонить Марии", None, [r"^позвонить", r"мари"]),
    ("встречу с Марией", None, [r"^встреча", r"мари"]),
    ("задачу про отчёт", None, [r"отч[её]т"]),
    ("демо по сайту", None, [r"^демо", r"сайт"]),
    ("созвон с Маяком", None, [r"^созвон", r"маяк"]),
    # подходящей нет, есть соседние — «не нашёл»
    ("встречу с дизайнером", None, []),
    ("созвон с юристами", None, []),
    ("встречу с Сергеем по бюджету", None, []),
    ("встречу с Натальей по CRM", None, []),  # есть только прошедшие
    ("созвон с Севером по CRM", None, []),  # есть «…по новому продукту»
    ("отправить смету Анне", None, []),  # есть «Согласовать смету с Анной»
    ("встречу с Алексеем по CRM", None, []),
    ("позвонить Наталье", None, []),
]

HIT_K = 5


def relevant(title: str, patterns: list[str]) -> bool:
    t = title.lower()
    return bool(patterns) and all(re.search(p, t) for p in patterns)


@dataclass
class SearchRow:
    query: str
    has_answer: bool
    match: str  # exact / similar / пусто
    count: int
    hit: bool
    exact_all_relevant: bool
    titles: list[str]


@dataclass
class TargetRow:
    text: str
    when: datetime | None
    gold: int
    outcome: str
    exact: list[str]
    similar: list[str]


@dataclass
class EvalResult:
    search: list[SearchRow] = field(default_factory=list)
    targets: list[TargetRow] = field(default_factory=list)
    vectors_computed: int = 0
    first_similar_s: float | None = None

    @property
    def hits(self) -> int:
        return sum(r.hit for r in self.search if r.has_answer)

    @property
    def with_answer(self) -> int:
        return sum(r.has_answer for r in self.search)

    @property
    def exact_without_answer(self) -> int:
        return sum(r.match == "exact" for r in self.search if not r.has_answer)

    @property
    def wrong_exact(self) -> list[str]:
        return [r.query for r in self.search if r.match == "exact" and not r.exact_all_relevant]

    def target_outcomes(self) -> Counter:
        return Counter(r.outcome for r in self.targets)


WRONG_RECORD = "ЧУЖАЯ запись"


def judge_target(exact_ids: list[UUID], similar_ids: list[UUID], gold: set[UUID]) -> str:
    """Исход для агента (agent-09): одна точная — действие, несколько — «какую?»,
    только похожие — «может, эту?», ничего — «не нашёл»."""
    if len(exact_ids) == 1:
        if exact_ids[0] not in gold:
            return WRONG_RECORD
        return "действие: верно" if len(gold) == 1 else "действие: одна из нескольких"
    if exact_ids:
        if not gold:
            return "переспрос лишний"
        if gold <= set(exact_ids):
            return "«какую?»: верно" if len(gold) > 1 else "переспрос лишний"
        return "«какую?» без нужной" if not gold & set(exact_ids) else "«какую?» неполный"
    if gold:
        return "«может, эту?» (точно не нашёл)" if similar_ids else "промах"
    return "«может, эту?»: верно" if similar_ids else "«не нашёл»: верно"


def run_eval(db: Session, user_id: UUID | None = None) -> EvalResult:
    """Загрузить стартовый набор новому пользователю и прогнать оба набора."""
    from search import find_target, search, vectors
    from services.bootstrap import bootstrap_user_data

    user_id = user_id or uuid4()
    bootstrap_user_data(db, user_id, "Europe/Moscow", now=NOW)
    result = EvalResult()

    counted = {"n": 0}
    original_ensure = vectors.ensure_vectors

    def counting_ensure(session, texts):
        n = original_ensure(session, texts)
        counted["n"] += n
        return n

    vectors.ensure_vectors = counting_ensure
    try:
        for query, types, patterns in SEARCH_SET:
            filters = SearchFilters(types=[RecordType(t) for t in types] if types else None)
            started = time.perf_counter()
            hits = search(db, user_id, query, filters, limit=HIT_K, now=NOW)
            elapsed = time.perf_counter() - started
            match = hits[0].match if hits else "пусто"
            if match == "similar" and result.first_similar_s is None:
                result.first_similar_s = elapsed
            titles = [h.record.title for h in hits]
            result.search.append(
                SearchRow(
                    query=query,
                    has_answer=bool(patterns),
                    match=match,
                    count=len(hits),
                    hit=any(relevant(t, patterns) for t in titles),
                    exact_all_relevant=all(relevant(t, patterns) for t in titles),
                    titles=titles,
                )
            )

        active = find_target(db, user_id, None, None, None, [RecordStatus.ACTIVE], limit=10_000)
        for text, when_kind, patterns in TARGET_SET:
            gold = [r for r in active.exact if relevant(r.title, patterns)]
            when = None
            if when_kind and gold:
                first = min(gold, key=lambda r: r.start)
                local = first.start.astimezone(TZ)
                if when_kind == "datetime":
                    when = local
                    gold = [r for r in gold if r.start == first.start]
                else:
                    when = local.replace(hour=0, minute=0, second=0, microsecond=0)
                    gold = [r for r in gold if r.start.astimezone(TZ).date() == local.date()]
            match = find_target(db, user_id, text, when, None, [RecordStatus.ACTIVE])
            result.targets.append(
                TargetRow(
                    text=text,
                    when=when,
                    gold=len(gold),
                    outcome=judge_target(
                        [r.id for r in match.exact],
                        [r.id for r in match.similar],
                        {r.id for r in gold},
                    ),
                    exact=[r.title for r in match.exact],
                    similar=[r.title for r in match.similar],
                )
            )
    finally:
        vectors.ensure_vectors = original_ensure
    result.vectors_computed = counted["n"]
    return result


def report(result: EvalResult) -> str:
    lines = [
        f"## Поиск: hit@{HIT_K} {result.hits}/{result.with_answer}; "
        f"«точно» на запросах без ответа: {result.exact_without_answer}; "
        f"неверные «точно»: {result.wrong_exact or 'нет'}",
        "",
        "| запрос | ответ есть | уровень | найдено | подходящая в выдаче | выдача |",
        "|---|---|---|---|---|---|",
    ]
    for r in result.search:
        shown = "; ".join(dict.fromkeys(r.titles)) or "—"
        lines.append(
            f"| {r.query} | {'да' if r.has_answer else 'нет'} | {r.match} | {r.count} | "
            f"{'да' if r.hit else '—'} | {shown} |"
        )
    outcomes = ", ".join(f"{k} {v}" for k, v in sorted(result.target_outcomes().items()))
    lines += [
        "",
        f"## Цели изменения: {outcomes}",
        "",
        "| цель | when | нужно | исход | exact | similar |",
        "|---|---|---|---|---|---|",
    ]
    for r in result.targets:
        when = r.when.strftime("%d.%m.%Y %H:%M") if r.when else "—"
        exact = "; ".join(dict.fromkeys(r.exact)) or "—"
        similar = "; ".join(dict.fromkeys(r.similar)) or "—"
        lines.append(
            f"| {r.text} | {when} | {r.gold} | {r.outcome} | {len(r.exact)}: {exact} | "
            f"{len(r.similar)}: {similar} |"
        )
    first = f"{result.first_similar_s:.2f} с" if result.first_similar_s is not None else "—"
    lines += [
        "",
        f"Посчитано векторов за прогон: {result.vectors_computed}; "
        f"первый поиск «похожих» (с загрузкой модели и векторами текстов): {first}",
    ]
    return "\n".join(lines)


# ---------- расширенный набор ----------

# Агент берёт у search() все точные (agent/actions.py, без limit) — здесь так же.
MAX_EXAMPLES = 6  # примеров ошибок на группу в отчёте


@dataclass
class ExtSearchRow:
    group: str
    query: str
    relevant: int  # сколько записей подходят по эталону
    level: str  # exact / similar / пусто
    hit: bool  # среди результатов есть подходящая
    wrong_exact: list[str]  # «точные» результаты, которые не подходят
    titles: list[str]


@dataclass
class ExtTargetRow:
    group: str
    text: str | None
    when: datetime | None
    gold: int
    outcome: str
    exact: list[str]
    similar: list[str]


@dataclass
class ExtendedResult:
    search: list[ExtSearchRow] = field(default_factory=list)
    targets: list[ExtTargetRow] = field(default_factory=list)

    @property
    def false_exact_without_answer(self) -> list[ExtSearchRow]:
        return [r for r in self.search if not r.relevant and r.level == "exact"]

    @property
    def wrong_records(self) -> list[ExtTargetRow]:
        return [r for r in self.targets if r.outcome == WRONG_RECORD]


def _in_filters(record, filters: SearchFilters, default_statuses) -> bool:
    """Те же фильтры, что обещает контракт: статус, тип, период по дате записи."""
    statuses = filters.status or default_statuses
    if record.status not in statuses:
        return False
    if filters.types and record.type not in filters.types:
        return False
    moment = record.start or record.deadline
    if filters.date_from is not None and (moment is None or moment < filters.date_from):
        return False
    return not (filters.date_to is not None and (moment is None or moment >= filters.date_to))


def _narrow_gold(rows, when: datetime | None, kind: str | None):
    if when is None:
        return rows
    local = [(r, r.start.astimezone(when.tzinfo)) for r in rows if r.start is not None]
    if kind == "datetime":
        return [r for r, m in local if (m.date(), m.hour, m.minute)
                == (when.date(), when.hour, when.minute)]
    return [r for r, m in local if m.date() == when.date()]


def run_extended(db: Session, user_id: UUID | None = None) -> ExtendedResult:
    """Стартовый набор новому пользователю, затем все случаи `scripts/search_cases.py`."""
    from schemas import Record
    from scripts.search_cases import parse_title, search_cases, target_cases
    from search import find_target, search
    from search.core import DEFAULT_SEARCH_STATUSES
    from services.bootstrap import bootstrap_user_data

    user_id = user_id or uuid4()
    bootstrap_user_data(db, user_id, "Europe/Moscow", now=NOW)
    from db import models

    records = [Record.model_validate(r) for r in db.query(models.Record).filter_by(user_id=user_id)]
    concepts = {t: parse_title(t) for t in {r.title for r in records}}
    result = ExtendedResult()

    for case in search_cases(NOW):
        gold = {
            r.id for r in records
            if _in_filters(r, case.filters, DEFAULT_SEARCH_STATUSES)
            and case.need.matches(concepts[r.title], r.type)
        }
        hits = search(db, user_id, case.query, case.filters, now=NOW)
        level = hits[0].match if hits else "пусто"
        result.search.append(ExtSearchRow(
            group=case.group,
            query=case.query,
            relevant=len(gold),
            level=level,
            hit=any(h.record.id in gold for h in hits),
            wrong_exact=[h.record.title for h in hits
                         if h.match == "exact" and h.record.id not in gold],
            titles=[h.record.title for h in hits],
        ))

    for case in target_cases(records, NOW):
        filters = case.filters or SearchFilters()
        candidates = [r for r in records if _in_filters(r, filters, case.statuses)
                      and case.need.matches(concepts[r.title], r.type)]
        gold = _narrow_gold(candidates, case.when, case.when_kind)
        match = find_target(db, user_id, case.text, case.when, case.filters, case.statuses)
        result.targets.append(ExtTargetRow(
            group=case.group,
            text=case.text,
            when=case.when,
            gold=len(gold),
            outcome=judge_target([r.id for r in match.exact], [r.id for r in match.similar],
                                 {r.id for r in gold}),
            exact=[r.title for r in match.exact],
            similar=[r.title for r in match.similar],
        ))
    return result


def _pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({100 * part / whole:.0f}%)" if whole else "—"


def report_extended(result: ExtendedResult) -> str:
    groups = list(dict.fromkeys(r.group for r in result.search))
    s = result.search
    answerable = [r for r in s if r.relevant]
    lines = [
        f"## Расширенный набор, поиск: {len(s)} запросов, с ответом {len(answerable)}",
        "",
        "- нашёл подходящую (все точные или до 10 похожих, как зовёт агент): "
        f"{_pct(sum(r.hit for r in answerable), len(answerable))}",
        f"- «точно» на запросах без ответа: {len(result.false_exact_without_answer)}",
        f"- запросов, где «точно» вернул неподходящую запись: "
        f"{sum(bool(r.wrong_exact) for r in s)}",
        "",
        "| группа | всего | с ответом | нашёл | «точно» | «похожие» | пусто "
        "| «точно» с чужими | «точно» без ответа |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for g in groups:
        rows = [r for r in s if r.group == g]
        ans = [r for r in rows if r.relevant]
        lines.append(
            f"| {g} | {len(rows)} | {len(ans)} | {_pct(sum(r.hit for r in ans), len(ans))} | "
            f"{sum(r.level == 'exact' for r in rows)} | {sum(r.level == 'similar' for r in rows)} "
            f"| {sum(r.level == 'пусто' for r in rows)} | {sum(bool(r.wrong_exact) for r in rows)} "
            f"| {sum(not r.relevant and r.level == 'exact' for r in rows)} |"
        )

    t = result.targets
    outcomes = sorted({r.outcome for r in t})
    lines += [
        "",
        f"## Расширенный набор, цели изменения: {len(t)}; чужих записей: "
        f"{len(result.wrong_records)}",
        "",
        "| группа | всего | " + " | ".join(outcomes) + " |",
        "|---|---|" + "---|" * len(outcomes),
    ]
    for g in dict.fromkeys(r.group for r in t):
        rows = [r for r in t if r.group == g]
        counts = Counter(r.outcome for r in rows)
        cells = " | ".join(str(counts[o]) for o in outcomes)
        lines.append(f"| {g} | {len(rows)} | {cells} |")

    lines += ["", "## Примеры ошибок", ""]
    for g in groups:
        bad = [r for r in s if r.group == g and (
            (r.relevant and not r.hit) or r.wrong_exact or (not r.relevant and r.level == "exact"))]
        for r in bad[:MAX_EXAMPLES]:
            why = ("не нашёл" if r.relevant and not r.hit else
                   "«точно» без ответа" if not r.relevant else "«точно» с чужими")
            shown = "; ".join(dict.fromkeys(r.wrong_exact or r.titles)) or "—"
            lines.append(f"- поиск · {g} · «{r.query}» ({r.level}, подходят {r.relevant}): "
                         f"{why} → {shown}")
    good = {"действие: верно", "«какую?»: верно", "«не нашёл»: верно", "«может, эту?»: верно"}
    for g in dict.fromkeys(r.group for r in t):
        bad = [r for r in t if r.group == g and r.outcome not in good]
        for r in bad[:MAX_EXAMPLES]:
            when = r.when.strftime("%d.%m.%Y %H:%M") if r.when else "—"
            got = "; ".join(dict.fromkeys(r.exact or r.similar)) or "—"
            lines.append(f"- цель · {g} · «{r.text}» {when} (нужно {r.gold}): {r.outcome} → "
                         f"exact {len(r.exact)}, similar {len(r.similar)}: {got}")
    return "\n".join(lines)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extended", action="store_true", help="и расширенный набор")
    args = parser.parse_args()

    from db.session import get_engine

    # Всё в одной транзакции, которая откатывается: пользователь и векторы в базе не остаются,
    # поэтому каждый прогон честно меряет и первый поиск «похожих» с подсчётом векторов.
    with get_engine().connect() as conn:
        trans = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            print(report(run_eval(session)))
            if args.extended:
                print()
                print(report_extended(run_extended(session)))
        finally:
            session.close()
            trans.rollback()


if __name__ == "__main__":
    main()
