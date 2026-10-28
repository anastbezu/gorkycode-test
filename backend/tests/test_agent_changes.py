"""Массовое изменение без базы: откат без точки сохранения (agent-07, ревью PR).

С настоящей сессией массовое изменение идёт в точке сохранения (см. test_agent_changes_db.py);
здесь — запасной путь, когда точки сохранения нет: уже изменённые записи возвращаются
сервисами, а если вернуть не удалось — исключение, и маршрут откатывает реплику целиком.
"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agent import changes as changes_module
from agent.changes import MassChangeError, _apply
from schemas import ActionResult, Record, RecordStatus, SetStatus, TargetRef
from services.records import RecordChange

NOW = datetime(2026, 10, 21, 10, tzinfo=UTC)


def record(n: int) -> Record:
    return Record(id=uuid4(), user_id=uuid4(), type="task", title=f"Запись {n}",
                  created_at=NOW)


def ok(rec: Record, before: str = "active") -> RecordChange:
    return RecordChange(ActionResult(action="set_status", ok=True, records=[rec]),
                        {"status": before})


FAIL = RecordChange(ActionResult(action="set_status", ok=False, error="сбой"))
CANCEL_ALL = SetStatus(target=TargetRef(all=True), status=RecordStatus.CANCELLED)


def run(records):
    return asyncio.run(_apply(None, uuid4(), CANCEL_ALL, records, NOW))


def test_failure_on_second_record_reverts_first(monkeypatch) -> None:
    first, second = record(1), record(2)
    calls = []

    def service(db, user_id, record_id, status):
        calls.append((record_id, status))
        if record_id == second.id:
            return FAIL
        return ok(first)

    monkeypatch.setattr(changes_module, "set_status", service)
    outcome = run([first, second])
    assert not outcome.result.ok
    assert calls == [(first.id, RecordStatus.CANCELLED), (second.id, RecordStatus.CANCELLED),
                     (first.id, RecordStatus.ACTIVE)]  # первую вернули


def test_failed_revert_raises_so_route_rolls_back(monkeypatch) -> None:
    """Сценарий ревью: первая отменена, вторая — ошибка, возврат первой — тоже ошибка."""
    first, second = record(1), record(2)
    calls = []

    def service(db, user_id, record_id, status):
        calls.append(record_id)
        if len(calls) == 1:
            return ok(first)
        return FAIL  # и вторая запись, и возврат первой

    monkeypatch.setattr(changes_module, "set_status", service)
    with pytest.raises(MassChangeError):
        run([first, second])
    assert calls == [first.id, second.id, first.id]
