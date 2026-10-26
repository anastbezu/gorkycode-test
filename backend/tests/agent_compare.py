"""Сравнение ответа агента с ожиданием кейса (agent-08).

Проверяются только поля, заданные в `Expect`: лишние поля ответа модели не мешают
(как `tool-args-match` в режиме partial у promptfoo). Даты сравниваются как моменты
времени в поясе пользователя с точностью до минуты, а не как строки.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from tests.agent_cases import ALL, NONE, Expect

ALL_TYPES = {"task", "meeting", "reminder"}
_MISSING = object()


@dataclass
class Observed:
    """Что получилось на одной реплике."""

    action: Any | None  # действие, дошедшее до исполнения (или вопрос AskUser); None — ничего
    ok: bool | None = None  # результат исполнения; None — исполнения не было
    awaiting: str | None = None  # ChatResponse.awaiting после реплики


def _parse_expected(value: str) -> datetime | date:
    if " " in value:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    return datetime.strptime(value, "%Y-%m-%d").date()


def _check_moment(name: str, expected: str, actual: Any, tz: ZoneInfo) -> list[str]:
    if actual is _MISSING:
        return [f"{name}: у действия нет такого поля"]
    if expected == NONE:
        return [] if actual is None else [f"{name}: ожидалось пусто, получено {_fmt(actual, tz)}"]
    if actual is None:
        return [f"{name}: ожидалось {expected}, получено пусто"]
    local = actual.astimezone(tz)
    want = _parse_expected(expected)
    if isinstance(want, datetime):
        got = local.replace(tzinfo=None, second=0, microsecond=0)
        return [] if got == want else [f"{name}: ожидалось {expected}, получено {_fmt(actual, tz)}"]
    return [] if local.date() == want else [
        f"{name}: ожидалась дата {expected}, получено {_fmt(actual, tz)}"
    ]


def _check_words(name: str, stems: tuple[str, ...], text: Any) -> list[str]:
    if not isinstance(text, str):
        return [f"{name}: нет текста"]
    lowered = text.lower()
    missing = [s for s in stems if not any(alt.lower() in lowered for alt in s.split("|"))]
    return [f"{name}: в «{text}» нет {', '.join(missing)}"] if missing else []


def _check_types(expected: tuple[str, ...] | str, actual: Any) -> list[str]:
    got = ALL_TYPES if not actual else {str(t) for t in actual}
    want = ALL_TYPES if expected == ALL else set(expected)
    if got == want:
        return []
    return [f"types: ожидалось {sorted(want)}, получено {sorted(got)}"]


def _fmt(value: Any, tz: ZoneInfo) -> str:
    if isinstance(value, datetime):
        return value.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    return repr(value)


def compare(expect: Expect, observed: Observed, tz: ZoneInfo) -> list[str]:
    """Список расхождений; пустой список — реплика прошла."""
    action = observed.action
    name = getattr(action, "action", "none") if action is not None else "none"
    if name not in expect.action.split("|"):
        return [f"действие: ожидалось {expect.action}, получено {name}"]

    problems: list[str] = []
    if expect.type is not None:
        got = getattr(action, "type", None)
        if str(got) != expect.type:
            problems.append(f"тип: ожидалось {expect.type}, получено {got}")
    if expect.title:
        problems += _check_words("название", expect.title, getattr(action, "title", None))
    for field in ("start", "end", "deadline", "date_from", "date_to"):
        expected = getattr(expect, field)
        if expected is not None:
            problems += _check_moment(field, expected, getattr(action, field, _MISSING), tz)
    if expect.start not in (None, NONE) and " " not in expect.start:
        # Дата без времени: модель должна сказать, что время не названо.
        if getattr(action, "time_given", None) is not False:
            problems.append("time_given: ожидалось false — время не названо")
    if expect.types is not None:
        problems += _check_types(expect.types, getattr(action, "types", None))
    if expect.query:
        problems += _check_words("запрос", expect.query, getattr(action, "query", None))
    filters = getattr(action, "filters", None)
    for field, expected in (("date_from", expect.query_from), ("date_to", expect.query_to)):
        if expected is not None:
            actual = getattr(filters, field, None) if filters is not None else None
            problems += _check_moment(f"фильтр {field}", expected, actual, tz)
    if expect.kind is not None and getattr(action, "kind", None) != expect.kind:
        problems.append(f"kind: ожидалось {expect.kind}, получено {getattr(action, 'kind', None)}")
    if expect.ok is not None and observed.ok is not expect.ok:
        problems.append(f"исполнение: ожидалось ok={expect.ok}, получено {observed.ok}")
    if expect.awaiting is not None:
        want = None if expect.awaiting == NONE else expect.awaiting
        if observed.awaiting != want:
            problems.append(f"ожидание ответа: ожидалось {want}, получено {observed.awaiting}")
    return problems


def describe(action: Any, tz: ZoneInfo) -> str:
    """Короткое описание действия для отчёта об упавших кейсах."""
    if action is None:
        return "ничего"
    data = action.model_dump(exclude_none=True, exclude_defaults=False)
    parts = []
    for key, value in data.items():
        if isinstance(value, datetime):
            value = _fmt(value, tz)
        parts.append(f"{key}={value}")
    return ", ".join(parts)
