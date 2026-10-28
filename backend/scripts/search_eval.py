"""Проверочный набор поиска (search-01): `search()` и `find_target()` на стартовом датасете.

Базовый набор — из замера техлида при выборе подхода: 30 запросов с ответом (примеры из задания, `docs/test-cases.md`
раздел 5 и свои — с другими формами слов, сокращениями, «е» вместо «ё»), 6 без ответа
и 24 цели изменения (однозначные, неоднозначные, без подходящей). Эталон — регулярные выражения
по названию: запись подходит, если в её названии (нижний регистр) находятся все.

Данные: стартовый набор нового пользователя (`bootstrap_user_data`), пояс Europe/Moscow,
«сейчас» = 21.10.2026 12:00, как в `docs/test-cases.md`.

Метрики:
- поиск: hit@5 — среди не больше 5 результатов `search(limit=5)` есть подходящая запись;
  «точно» на запросах без ответа — сколько раз `search()` ответил `exact` там, где ответа нет;
  точность «точно» — все ли `exact`-результаты подходящие;
- цели: исход `find_target(statuses=[active])` — действие над верной, чужая запись (ошибка,
  которой быть не должно), «какую?» с верными кандидатами, лишний переспрос, «не нашёл».

Запуск (нужны PostgreSQL с pgvector и модель в кэше Hugging Face):
    cd backend && uv run python -m scripts.search_eval
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
            hits = search(db, user_id, query, filters, limit=HIT_K)
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


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()

    from db.session import get_engine

    # Всё в одной транзакции, которая откатывается: пользователь и векторы в базе не остаются,
    # поэтому каждый прогон честно меряет и первый поиск «похожих» с подсчётом векторов.
    with get_engine().connect() as conn:
        trans = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            print(report(run_eval(session)))
        finally:
            session.close()
            trans.rollback()


if __name__ == "__main__":
    main()
