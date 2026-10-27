"""Ответы на изменение, смену статуса, откат и выбор цели (agent-07, agent-09).

Тексты — по смыслу примеров из постановки; окончательные формулировки задаёт
`docs/assistant-texts.md` (product-03).
"""

from schemas import Record, RecordStatus, SetStatus, UndoLast, UpdateRecord

from .changes import ChangeOutcome
from .presentation import MAX_SHOWN
from .replies import when_text

DONE_VERBS = {
    RecordStatus.DONE: "Отметил выполненной",
    RecordStatus.CANCELLED: "Отменил",
    RecordStatus.ACTIVE: "Вернул в активные",
}
CONFIRM_VERBS = {
    RecordStatus.DONE: "Отметить выполненными",
    RecordStatus.CANCELLED: "Отменить",
    RecordStatus.ACTIVE: "Вернуть в активные",
}


def describe(record: Record, timezone_name: str) -> str:
    when = when_text(record, timezone_name)
    return f"«{record.title}» {when}".strip()


def numbered(records: list[Record], timezone_name: str) -> str:
    """Номера — как на экране: `shown` = кандидаты в том же порядке (api.md)."""
    return "; ".join(
        f"{n}) {describe(record, timezone_name)}"
        for n, record in enumerate(records[:MAX_SHOWN], 1)
    )


def records_word(count: int) -> str:
    """«3 записи», «5 записей», «21 запись»."""
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} запись"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} записи"
    return f"{count} записей"


def _names(records: list[Record], timezone_name: str) -> str:
    return ", ".join(describe(record, timezone_name) for record in records)


def _choice_question(
    outcome: ChangeOutcome, action: UpdateRecord | SetStatus, timezone_name: str
) -> str:
    candidates = outcome.result.candidates
    if outcome.similar:
        if len(candidates) == 1:
            return f"Точно такой нет. Может, {describe(candidates[0], timezone_name)}?"
        return f"Точно такой нет. Может, одна из этих: {numbered(candidates, timezone_name)}?"
    if outcome.confirm and isinstance(action, SetStatus):
        verb = CONFIRM_VERBS[action.status]
        return f"{verb} {records_word(len(candidates))}: {numbered(candidates, timezone_name)}?"
    return f"Подходит несколько: {numbered(candidates, timezone_name)}. Какую?"


def _done(outcome: ChangeOutcome, action: UpdateRecord | SetStatus, timezone_name: str) -> str:
    records = outcome.result.records
    if isinstance(action, UpdateRecord):
        reply = f"Изменил: {_names(records, timezone_name)}."
        if outcome.result.conflicts:
            reply += f" В это же время: {_names(outcome.result.conflicts, timezone_name)}."
        return reply
    verb = DONE_VERBS[action.status]
    reply = f"{verb}: {_names(records, timezone_name)}."
    if action.status == RecordStatus.CANCELLED:
        reply += " Скажите «верни», если не то."
    return reply


def reply_for_change(
    outcome: ChangeOutcome, action: UpdateRecord | SetStatus | UndoLast, timezone_name: str
) -> str:
    result = outcome.result
    if isinstance(action, UndoLast):
        if not result.ok:
            return result.error or "Не получилось вернуть."
        if not result.restored:
            return "Вернул как было."
        return f"Вернул как было: {_names(result.restored, timezone_name)}."

    prefix = f"Вернул {_names(result.restored, timezone_name)}. " if result.restored else ""
    if result.candidates:
        return prefix + _choice_question(outcome, action, timezone_name)
    if not result.ok:
        return prefix + (result.error or "Не получилось изменить запись.")
    return prefix + _done(outcome, action, timezone_name)
