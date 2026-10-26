"""Прогон эталонных кейсов через агента (agent-08).

Реплики идут через настоящий `process_user_turn` с фиксированным «сейчас» (21.10.2026 10:00).
Подменяется только окружение агента:
- состояние разговора хранится в памяти (по одному разговору на кейс);
- создание записи проверяется настоящими бизнес-правилами `validate_create`, но в базу
  не пишется; список, поиск и справка возвращают пустой успешный результат.
Модель — какая передана: настоящий `get_action` в живом слое или сценарий в тестах.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import openai

from agent import agent as agent_module
from schemas import ActionResult, ConversationState, Record
from services.records import validate_create
from tests.agent_cases import CASES, NOW, TIMEZONE, Case, Expect
from tests.agent_compare import Observed, compare, describe

TZ = ZoneInfo(TIMEZONE)
FIXED_NOW = datetime.strptime(NOW, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)

Model = Callable[..., Awaitable[Any]]


@dataclass
class TurnReport:
    number: int
    text: str
    expect: Expect
    observed: Observed
    reply: str
    problems: list[str]


@dataclass
class CaseReport:
    case: Case
    turns: list[TurnReport] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(not t.problems for t in self.turns)


class Harness:
    """Окружение агента для прогона кейсов: состояние в памяти, сервисы без базы."""

    def __init__(self, monkeypatch, model: Model, *, pause: float = 0.0, retries: int = 2):
        self.model = model
        self.pause = pause
        self.retries = retries
        self.states: dict = {}
        self.raw: Any = None
        self.executed: Any = None
        self.result: ActionResult | None = None
        monkeypatch.setattr(agent_module, "get_or_create_conversation_state", self._load)
        monkeypatch.setattr(agent_module, "save_conversation_state", self._save)
        monkeypatch.setattr(agent_module, "get_record", lambda *args: None)
        monkeypatch.setattr(agent_module, "execute", self._execute)
        monkeypatch.setattr(agent_module, "get_action", self._get_action)

    def _load(self, db, conversation_id, user_id) -> ConversationState:
        state = self.states.setdefault(
            conversation_id, ConversationState(conversation_id=conversation_id, user_id=user_id)
        )
        return state.model_copy(deep=True)

    def _save(self, db, state: ConversationState) -> None:
        # Через JSON — как при сохранении в базу: черновик проходит ту же валидацию.
        self.states[state.conversation_id] = ConversationState.model_validate_json(
            state.model_dump_json()
        )

    async def _get_action(self, *args, **kwargs):
        for attempt in range(self.retries + 1):
            if self.pause:
                await asyncio.sleep(self.pause)
            try:
                self.raw = await self.model(*args, **kwargs)
                return self.raw
            except openai.APIError:
                if attempt == self.retries:
                    raise
                await asyncio.sleep(max(self.pause, 1.0) * 3)

    async def _execute(self, db, user_id, action, *, now=None) -> ActionResult:
        self.executed = action
        self.result = _fake_execute(user_id, action, now or FIXED_NOW)
        return self.result

    def run_case(self, case: Case) -> CaseReport:
        report = CaseReport(case)
        user_id, conversation_id = uuid4(), uuid4()
        for number, turn in enumerate(case.turns, 1):
            self.raw = self.executed = self.result = None
            response = asyncio.run(agent_module.process_user_turn(
                None, user_id, conversation_id, turn.text, TIMEZONE, now=FIXED_NOW,
            ))
            # До исполнения доходит действие с дописанным черновиком — его и сверяем;
            # если исполнения не было (вопрос, ошибка) — то, что вернула модель.
            observed = Observed(
                action=self.executed if self.executed is not None else self.raw,
                ok=self.result.ok if self.result is not None else None,
                awaiting=response.awaiting,
            )
            problems = compare(turn.expect, observed, TZ)
            report.turns.append(TurnReport(
                number, turn.text, turn.expect, observed, response.reply, problems,
            ))
            if problems:
                break  # дальше по диалогу проверять бессмысленно
        return report


def _fake_execute(user_id, action, now: datetime) -> ActionResult:
    if action.action == "create_record":
        if (error := validate_create(action, now)) is not None:
            return error
        record = Record(
            id=uuid4(), user_id=user_id, type=action.type, title=action.title,
            start=action.start, end=action.end, deadline=action.deadline,
            all_day=not action.time_given and action.start is not None, created_at=now,
        )
        return ActionResult(action="create_record", ok=True, records=[record])
    if action.action in {"list_records", "search_records", "help"}:
        return ActionResult(action=action.action, ok=True)
    return ActionResult(action=action.action, ok=False, error=f"нет действия {action.action}")


def select_cases(sections: str | None) -> list[Case]:
    """Все кейсы или только разделы из строки «2,3»."""
    if not sections:
        return list(CASES)
    wanted = {s.strip() for s in sections.split(",") if s.strip()}
    return [c for c in CASES if c.section in wanted]


def describe_expect(expect: Expect) -> str:
    parts = [f"action={expect.action}"]
    for key, value in vars(expect).items():
        if key != "action" and value not in (None, ()):
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def render(reports: list[CaseReport], skipped: list[Case]) -> str:
    total = len(reports)
    passed = sum(r.passed for r in reports)
    rate = passed / total * 100 if total else 0.0
    lines = [f"Живой прогон: прошло {passed} из {total} ({rate:.1f}%), "
             f"пропущено с причиной: {len(skipped)}"]
    for report in reports:
        if report.passed:
            continue
        turn = report.turns[-1]
        lines += [
            "",
            f"УПАЛ {report.case.id}: «{turn.text}» (реплика {turn.number})",
            f"  ожидалось: {describe_expect(turn.expect)}",
            f"  получено:  {describe(turn.observed.action, TZ)}; ok={turn.observed.ok}, "
            f"awaiting={turn.observed.awaiting}",
            f"  ответ:     {turn.reply}",
            *(f"  - {p}" for p in turn.problems),
        ]
    return "\n".join(lines)
