"""`search()` и `find_target()` — контракт `docs/contracts/search.md`, устройство —
`docs/modules/search.md`.

Обе функции устроены одинаково:
1. SQL отбирает записи пользователя по фильтрам (тип, период, статус) — до сравнения текста;
2. уровень «точно» — каждое значимое слово запроса есть в названии (`search.text`);
3. «точно» пусто — уровень «похожие» по векторам названий (`search.vectors`).

Пример: у пользователя «Позвонить Дмитрием» (искажённый падеж из датасета).
- `search("Дмитрий бюджет")` — «точно» есть: «Напомнить Дмитрию про бюджет»;
- `search("звонок Дмитрию")` — «звонок» не совпадает ни с «позвонить» по основе, ни почти
  по буквам, поэтому «точно» пусто; по смыслу «Позвонить Дмитрием» близко — `similar`;
- `search("встреча с дизайнером")` — дизайнеров нет: похожие ниже порога, ответ пустой.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import models
from schemas import Record, RecordStatus, RecordType, SearchFilters, SearchHit, TargetMatch

from . import embeddings, vectors
from .text import QueryWords, TitleWords, is_exact

# Порог уровня «похожие» — косинус frida, снят на проверочном наборе (scripts/search_eval.py)
# 2026-10-27. У запросов, которые не нашлись «точно», но ответ в данных есть, лучший результат —
# от 0,485 («мобилка» → «…по мобильному приложению») до 0,82; у запросов без ответа — до 0,464
# («встреча с дизайнером»). Порог взят ниже обоих: пропустить настоящую похожую запись хуже,
# чем ответить «точно не нашёл, похожие: …» там, где ответа нет. Набор синтетический —
# переснять на живых фразах.
SIMILAR_MIN_SCORE = 0.45

# search(): сколько похожих показать. Точные не ограничены — как список за период.
SIMILAR_LIMIT = 10

# find_target(): сколько похожих предложить вопросом «Может, эту?» (контракт).
TARGET_SIMILAR_LIMIT = 3

# Без фильтра статуса поиск не показывает отменённые — как список за период (data-model.md).
DEFAULT_SEARCH_STATUSES = (RecordStatus.ACTIVE, RecordStatus.DONE)


def _record_date(row: models.Record) -> datetime | None:
    """Дата записи: начало, а у задачи без начала — срок. Как сортирует список за период."""
    return row.start if row.start is not None else row.deadline


def _nearest_first(now: datetime):
    """Ключ сортировки: сначала будущие от ближних к дальним, затем прошедшие от новых
    к старым, без даты — в конце. «Сейчас» и позже — будущие.

    «Задачи по Максиму» за 4 года: наверху завтрашняя, а не запись через год.
    """

    def key(row: models.Record) -> tuple:
        d = _record_date(row)
        if d is None:
            return (2, 0.0)
        if d >= now:
            return (0, d.timestamp())
        return (1, -d.timestamp())

    return key


def _earliest_first(row: models.Record) -> tuple:
    d = _record_date(row)
    return (d is None, d.timestamp() if d else 0.0)


def _filtered_records(
    db: Session,
    user_id: UUID,
    *,
    statuses: Iterable[RecordStatus],
    types: list[RecordType] | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[models.Record]:
    """Записи пользователя по фильтрам. Период — по дате записи, `[date_from, date_to)`."""
    m = models.Record
    when = func.coalesce(m.start, m.deadline)
    stmt = select(m).where(m.user_id == user_id, m.status.in_(list(statuses)))
    if types:
        stmt = stmt.where(m.type.in_(types))
    if date_from is not None:
        stmt = stmt.where(when >= date_from)
    if date_to is not None:
        stmt = stmt.where(when < date_to)
    return list(db.scalars(stmt))


def _exact_by_words(query: str, rows: list[models.Record]) -> list[models.Record]:
    words = QueryWords(query)
    title_words: dict[str, TitleWords] = {}
    matched = []
    for row in rows:
        if row.title not in title_words:
            title_words[row.title] = TitleWords(row.title)
        if is_exact(words, title_words[row.title], row.type):
            matched.append(row)
    return matched


def _similar_by_meaning(
    db: Session, query: str, rows: list[models.Record]
) -> list[tuple[models.Record, float]]:
    """Записи, близкие к запросу по смыслу, со сходством не ниже порога."""
    if not rows or not query.strip():
        return []
    titles = list({row.title for row in rows})
    vectors.ensure_vectors(db, titles)
    query_vector = embeddings.embed_queries([query])[0]
    scores = vectors.similarities(db, query_vector, titles)
    return [(row, scores[row.title]) for row in rows if scores[row.title] >= SIMILAR_MIN_SCORE]


def search(
    db: Session,
    user_id: UUID,
    query: str,
    filters: SearchFilters,
    limit: int | None = None,
    now: datetime | None = None,
) -> list[SearchHit]:
    """Вопрос пользователя: «точно», иначе «похожие», иначе пусто.

    Порядок — ближайшие будущие, затем прошедшие от новых (`_nearest_first`). Точные — все,
    сколько нашлось, если `limit` не задан; похожие — не больше `SIMILAR_LIMIT`.
    """
    nearest_first = _nearest_first(now or datetime.now(UTC))
    rows = _filtered_records(
        db,
        user_id,
        statuses=filters.status or DEFAULT_SEARCH_STATUSES,
        types=filters.types,
        date_from=filters.date_from,
        date_to=filters.date_to,
    )

    exact = _exact_by_words(query, rows)
    if exact:
        # Точные равноценны: при `limit` остаются ближайшие.
        chosen = sorted(exact, key=nearest_first)[:limit]
        return [
            SearchHit(record=Record.model_validate(row), score=1.0, match="exact")
            for row in chosen
        ]

    similar = _similar_by_meaning(db, query, rows)
    # При переполнении остаются самые близкие по смыслу, на экране они идут по дате, как точные.
    similar_limit = SIMILAR_LIMIT if limit is None else min(limit, SIMILAR_LIMIT)
    closest = sorted(similar, key=lambda pair: (-pair[1], nearest_first(pair[0])))
    closest = closest[:similar_limit]
    closest.sort(key=lambda pair: nearest_first(pair[0]))
    return [
        SearchHit(record=Record.model_validate(row), score=score, match="similar")
        for row, score in closest
    ]


def _same_day(row: models.Record, when: datetime) -> bool:
    return _record_date(row).astimezone(when.tzinfo).date() == when.date()


def _same_time(row: models.Record, when: datetime) -> bool:
    # У записи «на весь день» времени нет — по времени она не совпадает ни с чем.
    if row.all_day:
        return False
    local = _record_date(row).astimezone(when.tzinfo)
    return (local.hour, local.minute) == (when.hour, when.minute)


def _narrow_by_when(rows: list[models.Record], when: datetime) -> list[models.Record]:
    """Сужение по названному времени: тот же день и время → тот же день → то же время.

    День и время сравниваются в поясе `when` — это пояс пользователя.
    `when` ровно в 00:00 — назван только день («в пятницу»): так агент передаёт день без
    времени (как `start` дня без времени, agent-tools.md), и сравнивается только день —
    иначе «в пятницу» нашло бы записи в 00:00 других дней.
    Подошла ступень — остаются только её записи; не подошла ни одна — пусто.
    """
    dated = [row for row in rows if _record_date(row) is not None]
    if (when.hour, when.minute) == (0, 0):
        return [row for row in dated if _same_day(row, when)]
    for matches in (
        lambda r: _same_day(r, when) and _same_time(r, when),
        lambda r: _same_day(r, when),
        lambda r: _same_time(r, when),
    ):
        narrowed = [row for row in dated if matches(row)]
        if narrowed:
            return narrowed
    return []


def _closest_in_time(rows: list[models.Record], when: datetime, n: int) -> list[models.Record]:
    def distance(row: models.Record) -> float:
        d = _record_date(row)
        return abs((d - when).total_seconds()) if d else float("inf")

    return sorted(rows, key=distance)[:n]


def _to_records(rows: Iterable[models.Record]) -> list[Record]:
    return [Record.model_validate(row) for row in rows]


def find_target(
    db: Session,
    user_id: UUID,
    text: str | None,
    when: datetime | None,
    filters: SearchFilters | None,
    statuses: list[RecordStatus],
    limit: int = 21,
) -> TargetMatch:
    """Какую запись менять. `exact` — можно действовать; `similar` — только спросить."""
    rows = _filtered_records(
        db,
        user_id,
        statuses=statuses,
        types=filters.types if filters else None,
        date_from=filters.date_from if filters else None,
        date_to=filters.date_to if filters else None,
    )

    # «Отмени всё на завтра»: описания нет — все записи по фильтрам и времени.
    if text is None:
        exact = _narrow_by_when(rows, when) if when is not None else rows
        return TargetMatch(exact=_to_records(sorted(exact, key=_earliest_first)[:limit]))

    by_words = _exact_by_words(text, rows)
    if by_words:
        if when is None:
            exact = by_words
        else:
            exact = _narrow_by_when(by_words, when)
            if not exact:
                # Слова совпали, время — нет: не действуем, а спрашиваем про ближайшие по времени.
                similar = _closest_in_time(by_words, when, TARGET_SIMILAR_LIMIT)
                return TargetMatch(similar=_to_records(sorted(similar, key=_earliest_first)))
        return TargetMatch(exact=_to_records(sorted(exact, key=_earliest_first)[:limit]))

    # Точных нет: похожие по смыслу — только для вопроса «Может, эту?», никогда не в exact.
    similar = _similar_by_meaning(db, text, rows)
    closest = sorted(similar, key=lambda pair: (-pair[1], _earliest_first(pair[0])))
    chosen = [row for row, _ in closest[:TARGET_SIMILAR_LIMIT]]
    return TargetMatch(similar=_to_records(sorted(chosen, key=_earliest_first)))
