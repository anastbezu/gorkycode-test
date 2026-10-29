"""Прогон эталонных кейсов через агента (agent-08).

Реплики идут через настоящий `process_user_turn` с фиксированным «сейчас» (21.10.2026 10:00).
Два режима окружения:
- с базой (`db=` — сессия тестовой PostgreSQL): настоящие сервисы записей и состояния
  разговора, ничего не подменяется, кроме модели. Так проверяется быстрый слой в CI;
- без базы (живой прогон на машине разработчика): состояние разговора — в памяти, создание
  проверяется настоящими бизнес-правилами `validate_create`, но в базу не пишется; список,
  поиск и справка возвращают пустой успешный результат.
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
from db import models
from schemas import ActionResult, ConversationState, Record
from services.records import validate_create
from tests.agent_cases import CASES, NEEDS_DB, NOW, TIMEZONE, Case, Expect
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
    """Окружение агента для прогона кейсов."""

    def __init__(self, monkeypatch, model: Model, *, db=None, pause: float = 0.0,
                 retries: int = 2):
        self.model = model
        self.db = db
        self.pause = pause
        self.retries = retries
        self.states: dict = {}
        self.raw: Any = None
        self.executed: Any = None
        self.result: ActionResult | None = None
        self.provider_failures = 0  # кейсы подряд, где модель не ответила

        if db is None:
            monkeypatch.setattr(agent_module, "get_or_create_conversation_state", self._load)
            monkeypatch.setattr(agent_module, "save_conversation_state", self._save)
            monkeypatch.setattr(agent_module, "get_record", lambda *args: None)
            execute = self._fake_execute
        else:
            execute = agent_module.execute  # настоящие сервисы на тестовой базе

        async def tracked_execute(db_, user_id, action, *, now=None) -> ActionResult:
            # Запоминаем, что дошло до исполнения и чем закончилось.
            self.executed = action
            self.result = await execute(db_, user_id, action, now=now)
            return self.result

        monkeypatch.setattr(agent_module, "execute", tracked_execute)

        real_change = agent_module.execute_change

        async def tracked_change(db_, user_id, action, state, *, now):
            # Изменения идут мимо execute (нужны цель из состояния и прежние значения).
            self.executed = action
            outcome = await real_change(db_, user_id, action, state, now=now)
            # Сверяем исполненное: код мог поправить действие («на пятницу» — прежнее время).
            self.executed = outcome.applied or action
            self.result = outcome.result
            return outcome

        monkeypatch.setattr(agent_module, "execute_change", tracked_change)
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

    async def _fake_execute(self, db, user_id, action, *, now=None) -> ActionResult:
        return _fake_execute(user_id, action, now or FIXED_NOW)

    async def _get_action(self, *args, **kwargs):
        for attempt in range(self.retries + 1):
            if self.pause:
                await asyncio.sleep(self.pause)
            try:
                self.raw = await self.model(*args, **kwargs)
                self.provider_failures = 0
                return self.raw
            except openai.APIError:
                if attempt == self.retries:
                    self.provider_failures += 1
                    raise
                await asyncio.sleep(max(self.pause, 1.0) * 3)

    def run_turn(self, text: str, user_id, conversation_id) -> tuple[Observed, str]:
        """Одна реплика в разговоре: что дошло до исполнения и текст ответа."""
        self.raw = self.executed = self.result = None
        response = asyncio.run(agent_module.process_user_turn(
            self.db, user_id, conversation_id, text, TIMEZONE, now=FIXED_NOW,
        ))
        # До исполнения доходит действие с дописанным черновиком — его и сверяем;
        # если исполнения не было (вопрос, ошибка) — то, что вернула модель.
        observed = Observed(
            action=self.executed if self.executed is not None else self.raw,
            ok=self.result.ok if self.result is not None else None,
            awaiting=response.awaiting,
        )
        return observed, response.reply

    def seed(self, user_id, case: Case) -> None:
        """Записи-предусловия кейса (раздел 7, пересечения) — в тестовую базу."""
        for item in case.records:
            start = _local(item.start)
            self.db.add(models.Record(
                user_id=user_id, type=item.type, title=item.title, start=start,
                deadline=_local(item.deadline), all_day=False,
            ))
        self.db.flush()

    def run_case(self, case: Case) -> CaseReport:
        report = CaseReport(case)
        user_id, conversation_id = uuid4(), uuid4()
        if case.needs_db:
            if self.db is None:
                raise ValueError(f"кейсу {case.id} нужна база: Harness(db=...)")
            self.seed(user_id, case)
        for number, turn in enumerate(case.turns, 1):
            observed, reply = self.run_turn(turn.text, user_id, conversation_id)
            problems = compare(turn.expect, observed, TZ)
            report.turns.append(TurnReport(number, turn.text, turn.expect, observed, reply,
                                           problems))
            if problems:
                break  # дальше по диалогу проверять бессмысленно
        return report


def _local(value: str | None) -> datetime | None:
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=TZ) if value else None


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


def skip_reason(case: Case, with_db: bool) -> str | None:
    """Почему кейс не прогоняется: своя причина или нет базы для изменений."""
    if case.skip is not None:
        return case.skip
    if case.needs_db and not with_db:
        return NEEDS_DB
    return None


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
