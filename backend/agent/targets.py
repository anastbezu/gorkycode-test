"""Цель изменения: какую запись менять (agent-07, agent-09).

`TargetRef` переводится в записи так (agent-tools.md, «Цель изменения»; search.md):
- `index` — запись `shown[index - 1]`, `focus` — `focus_record_id`; без поиска;
- `all` без описания — все записи из `shown` (ответ «да» на «Отменить 3 созвона?»);
- `text`, `when`, `filters` — `find_target()` модуля поиска. Агент сам записи не ищет
  и кандидатов не сортирует.

Исход — `Target`: записи для действия, кандидаты для выбора или текст ошибки.
"""

from asyncio import to_thread
from dataclasses import dataclass, field
from uuid import UUID

from schemas import ConversationState, Record, RecordStatus, TargetRef
from services.records import get_record
from services.search_stub import find_target  # TODO: find_target() из модуля поиска Родиона

MAX_ALL = 20  # «отмени все …» — больше 20 записей не трогаем, просим уточнить


@dataclass
class Target:
    """Исполнить над `records`, спросить по `candidates` или ответить `error`."""

    records: list[Record] = field(default_factory=list)
    candidates: list[Record] = field(default_factory=list)
    similar: bool = False  # кандидаты только похожи — «Точно такой нет. Может, эту?»
    confirm: bool = False  # несколько записей одной командой — «Отменить 3 …?»
    error: str | None = None


async def _owned(db, user_id: UUID, ids: list[UUID]) -> list[Record]:
    records = []
    for record_id in ids:
        record = await to_thread(get_record, db, user_id, record_id)
        if record is not None:
            records.append(record)
    return records


def _described(target: TargetRef) -> bool:
    return bool(target.text) or target.when is not None or target.filters is not None


async def resolve_target(
    db,
    user_id: UUID,
    target: TargetRef,
    state: ConversationState,
    statuses: list[RecordStatus],
) -> Target:
    if target.index is not None:
        number = target.index
        if 1 <= number <= len(state.shown):
            records = await _owned(db, user_id, [state.shown[number - 1]])
            if records:
                return Target(records=records)
        return Target(error=f"В показанном списке нет записи № {number}.")

    if target.focus:
        if state.focus_record_id is not None:
            records = await _owned(db, user_id, [state.focus_record_id])
            if records:
                return Target(records=records)
        return Target(error="Какую запись? Назовите её или выберите из списка.")

    if target.all and not _described(target):
        # «Да», «все» на подтверждение: все записи с экрана.
        records = await _owned(db, user_id, list(state.shown))
        if records:
            return Target(records=records)
        return Target(error="Не понял, какие записи. Назовите их.")

    if not _described(target):
        return Target(error="Какую запись? Назовите её или выберите из списка.")

    match = await to_thread(
        find_target, db, user_id, target.text, target.when, target.filters, statuses, MAX_ALL + 1
    )
    if target.all:
        # Массовое действие — только точные записи; похожие не предлагаем.
        if len(match.exact) > MAX_ALL:
            return Target(error="Слишком много записей. Уточните, какие.")
        if len(match.exact) == 1:
            return Target(records=match.exact)
        if match.exact:
            return Target(candidates=match.exact, confirm=True)
        return Target(error=not_found(target))
    if len(match.exact) == 1:
        return Target(records=match.exact)
    if match.exact:
        return Target(candidates=match.exact)
    if match.similar:
        return Target(candidates=match.similar, similar=True)
    return Target(error=not_found(target))


def not_found(target: TargetRef) -> str:
    if target.text:
        return f"Не нашёл «{target.text}»."
    return "Не нашёл такой записи."
