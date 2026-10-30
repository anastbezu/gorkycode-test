"""Кейсы агента: формат набора в JSON и загрузка с проверкой.

Набор — файл `eval/datasets/agent/<имя>.json`:

    {"dataset": "test-cases", "source": "docs/test-cases.md", "author": "…",
     "now": "2026-10-21 10:00", "timezone": "Europe/Moscow",
     "cases": [{"id": "1.1", "category": "…", "turns": [{"text": "…", "expect": {…}}]}]}

Поля кейса: `id`, `category` (раздел или категория подвоха — разрез в отчёте), `turns`,
необязательные `records` (записи пользователя до первой реплики), `db` (проверяется только
с базой), `skip` (причина пропуска), `ref` (раздел 9 test-cases.md: строка «Выражение»), `note`.

Как записывать ожидание (`expect`) — проверяются только заданные поля, лишние поля ответа
модели кейс не роняют:
- `action` — имя инструмента; несколько допустимых через «|»: "list_records|ask_user";
  "none" — ничего не исполнено и модель не вызывалась (отказ «не надо» без модели);
- `type` — task / meeting / reminder;
- `title`, `query` — список основ слов, без регистра; каждая должна встретиться
  в названии (запросе); альтернативы через «|»: ["КП|коммерческ"];
- `start`, `end`, `deadline`, `date_from`, `date_to` — локальное время пользователя:
  "2026-10-22 10:00" — до минуты; "2026-10-22" — только дата
  (для `start` это ещё и «время не названо», time_given=false); "none" — поля нет;
- `query_from`, `query_to` — период фильтра поиска, так же;
- `types` — типы списка (список), "all" — все типы;
- `kind` — у help: help / offtopic;
- `status` — у set_status: done / cancelled / active; `replaces_last` — «нет, не этот, а тот»;
- цель изменения: `target_index` — номер из «Показано», `target_focus` — «её»,
  `target_all` — «все …» / «да» на подтверждение, `target_text` — основы слов описания;
- `ok` — успешно ли исполнено действие; `awaiting` — чего ждёт ассистент после реплики:
  answer / choice / confirm / time или "none".

Записи `records`: `type`, `title`, `start` и/или `deadline` — локальное время, как в `expect`.

Загрузка проверяет набор и падает с номером кейса: неизвестное поле, неизвестный инструмент,
дата не в формате, поле, которого у инструмента нет (`target_index` у `create_record`),
повтор `id`. Это проверка кейсов, которые пишет модель-генератор.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from schemas import actions as action_schemas

NONE = "none"
ALL = "all"

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
TEST_CASES_FILE = DATASETS_DIR / "agent" / "test-cases.json"

NEEDS_DB = "нужна база: TEST_DATABASE_URL (изменения и пересечения проверяются на записях)"


@dataclass(frozen=True)
class Expect:
    action: str
    type: str | None = None
    title: tuple[str, ...] = ()
    start: str | None = None
    end: str | None = None
    deadline: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    types: tuple[str, ...] | str | None = None
    query: tuple[str, ...] = ()
    query_from: str | None = None
    query_to: str | None = None
    kind: str | None = None
    status: str | None = None
    replaces_last: bool | None = None
    target_index: int | None = None
    target_focus: bool | None = None
    target_all: bool | None = None
    target_text: tuple[str, ...] = ()
    ok: bool | None = None
    awaiting: str | None = None


@dataclass(frozen=True)
class Seed:
    """Запись пользователя до начала кейса; время — локальное, как в `Expect`."""

    type: str
    title: str
    start: str | None = None
    deadline: str | None = None


@dataclass(frozen=True)
class Turn:
    text: str
    expect: Expect


@dataclass(frozen=True)
class Case:
    id: str  # номер ровно как в test-cases.md; для раздела 9 — "9:<выражение>"
    turns: tuple[Turn, ...]
    skip: str | None = None
    ref: str | None = None  # раздел 9: строка «Выражение» из таблицы
    records: tuple[Seed, ...] = ()  # записи пользователя до первой реплики
    db: bool = False  # проверяется только с базой (изменения, пересечения)
    note: str = field(default="", compare=False)
    category: str = field(default="", compare=False)

    @property
    def section(self) -> str:
        return self.id.split(".")[0].split(":")[0]

    @property
    def needs_db(self) -> bool:
        return self.db or bool(self.records)


@dataclass(frozen=True)
class Dataset:
    name: str
    source: str
    author: str
    now: str
    timezone: str
    cases: tuple[Case, ...]


# ---------- проверка JSON ----------

# Инструмент → поля его действия (схемы в backend/schemas/actions.py).
TOOLS: dict[str, set[str]] = {
    model.model_fields["action"].default: set(model.model_fields)
    for model in (
        action_schemas.CreateRecord, action_schemas.ListRecords, action_schemas.SearchRecords,
        action_schemas.UpdateRecord, action_schemas.SetStatus, action_schemas.UndoLast,
        action_schemas.AskUser, action_schemas.Help,
    )
}

# Поле ожидания → поле действия, которое оно проверяет; None — результат, а не аргумент.
EXPECT_TO_ACTION = {
    "type": "type", "title": "title", "start": "start", "end": "end", "deadline": "deadline",
    "date_from": "date_from", "date_to": "date_to", "types": "types", "query": "query",
    "query_from": "filters", "query_to": "filters", "kind": "kind", "status": "status",
    "replaces_last": "replaces_last", "target_index": "target", "target_focus": "target",
    "target_all": "target", "target_text": "target", "ok": None, "awaiting": None,
}

_MOMENT = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$")
_AWAITING = {"answer", "choice", "confirm", "time", NONE}


def _moment(value: str | None) -> str | None:
    if value is not None and value != NONE and not _MOMENT.match(value):
        raise ValueError(f"дата «{value}» не в формате ГГГГ-ММ-ДД или ГГГГ-ММ-ДД ЧЧ:ММ")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectIn(_Strict):
    action: str
    type: str | None = Field(None, pattern="^(task|meeting|reminder)$")
    title: list[str] = []
    start: str | None = None
    end: str | None = None
    deadline: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    types: list[str] | str | None = None
    query: list[str] = []
    query_from: str | None = None
    query_to: str | None = None
    kind: str | None = Field(None, pattern="^(help|offtopic)$")
    status: str | None = Field(None, pattern="^(done|cancelled|active)$")
    replaces_last: bool | None = None
    target_index: int | None = Field(None, ge=1)
    target_focus: bool | None = None
    target_all: bool | None = None
    target_text: list[str] = []
    ok: bool | None = None
    awaiting: str | None = None

    _dates = field_validator(
        "start", "end", "deadline", "date_from", "date_to", "query_from", "query_to"
    )(classmethod(lambda cls, v: _moment(v)))

    @field_validator("action")
    @classmethod
    def _known_tools(cls, v: str) -> str:
        unknown = [name for name in v.split("|") if name not in TOOLS and name != NONE]
        if unknown:
            raise ValueError(f"неизвестный инструмент {unknown}; есть: {sorted(TOOLS)}")
        return v

    @field_validator("types")
    @classmethod
    def _types(cls, v):
        if isinstance(v, str) and v != ALL:
            raise ValueError('types — список типов или "all"')
        if isinstance(v, list) and not set(v) <= {"task", "meeting", "reminder"}:
            raise ValueError(f"неизвестный тип в {v}")
        return v

    @field_validator("awaiting")
    @classmethod
    def _awaiting(cls, v):
        if v is not None and v not in _AWAITING:
            raise ValueError(f"awaiting — одно из {sorted(_AWAITING)}")
        return v

    def check_fields_belong_to_tool(self) -> None:
        tools = self.action.split("|")
        for name in self.model_fields_set - {"action"}:
            arg = EXPECT_TO_ACTION[name]
            if arg is not None and not any(arg in TOOLS.get(t, ()) for t in tools):
                raise ValueError(
                    f"поле «{name}» не проверить у {self.action}: у действия нет «{arg}»")


class SeedIn(_Strict):
    type: str = Field(pattern="^(task|meeting|reminder)$")
    title: str
    start: str | None = None
    deadline: str | None = None

    _dates = field_validator("start", "deadline")(classmethod(lambda cls, v: _moment(v)))


class TurnIn(_Strict):
    text: str = Field(min_length=1)
    expect: ExpectIn


class CaseIn(_Strict):
    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    turns: list[TurnIn] = Field(min_length=1)
    records: list[SeedIn] = []
    db: bool = False
    skip: str | None = None
    ref: str | None = None
    note: str = ""


class DatasetIn(_Strict):
    dataset: str
    source: str
    author: str
    now: str = Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
    timezone: str
    cases: list[CaseIn] = Field(min_length=1)


class DatasetError(ValueError):
    pass


def _to_case(item: CaseIn) -> Case:
    def expect(e: ExpectIn) -> Expect:
        data = e.model_dump(exclude_unset=True)
        for key in ("title", "query", "target_text"):
            if key in data:
                data[key] = tuple(data[key])
        if isinstance(data.get("types"), list):
            data["types"] = tuple(data["types"])
        return Expect(**data)

    return Case(
        id=item.id,
        turns=tuple(Turn(t.text, expect(t.expect)) for t in item.turns),
        skip=item.skip,
        ref=item.ref,
        records=tuple(Seed(**s.model_dump()) for s in item.records),
        db=item.db,
        note=item.note,
        category=item.category,
    )


def load_dataset(path: Path) -> Dataset:
    """Набор из файла; ошибка — `DatasetError` с файлом и номером кейса."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        data = DatasetIn.model_validate(raw)
    except ValidationError as exc:
        raise DatasetError(f"{path}: {exc}") from exc
    seen: set[str] = set()
    for item in data.cases:
        if item.id in seen:
            raise DatasetError(f"{path}: кейс {item.id} повторяется")
        seen.add(item.id)
        for number, turn in enumerate(item.turns, 1):
            try:
                turn.expect.check_fields_belong_to_tool()
            except ValueError as exc:
                raise DatasetError(f"{path}: кейс {item.id}, реплика {number}: {exc}") from exc
    return Dataset(
        name=data.dataset, source=data.source, author=data.author, now=data.now,
        timezone=data.timezone, cases=tuple(_to_case(c) for c in data.cases),
    )


def agent_datasets() -> list[Path]:
    return sorted((DATASETS_DIR / "agent").glob("*.json"))


TEST_CASES = load_dataset(TEST_CASES_FILE)
CASES = TEST_CASES.cases
NOW = TEST_CASES.now
TIMEZONE = TEST_CASES.timezone
