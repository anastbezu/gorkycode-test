"""Общий порядок групп для ответа и ссылок через ConversationState.shown."""

from dataclasses import dataclass
from datetime import datetime

from schemas import Record

MAX_SHOWN = 10


def record_moment(record: Record) -> datetime:
    return record.start or record.deadline or record.created_at


@dataclass(frozen=True)
class RecordGroup:
    record: Record
    count: int


def group_records(records: list[Record]) -> list[RecordGroup]:
    """Порядок первого появления названия; представитель группы — последний по дате.

    Разные типы/статусы не склеиваем: выполненная задача и активная встреча
    с одинаковым названием должны оставаться разными целями.
    """
    groups: dict[tuple, list[Record]] = {}
    for record in records:
        groups.setdefault((record.title, record.type, record.status), []).append(record)
    return [RecordGroup(max(items, key=record_moment), len(items)) for items in groups.values()]


def shown_records(records: list[Record]) -> list[Record]:
    return [group.record for group in group_records(records)[:MAX_SHOWN]]
