"""Временный диспетчер чата без LLM (backend-02b).

Пока агент не подключён к `/api/chat` (задача agent-05), реплика разбирается простыми
правилами и сразу идёт в настоящие сервисы — ответ приходит из базы данных:
- «что у меня …», «покажи …», «какие …», «план…» → список за период (сегодня / завтра / неделя);
- всё остальное → задача без даты с текстом реплики.

agent-05 заменяет вызов `handle_without_llm` на `agent.process_user_turn` — у них одинаковый
результат (`ChatResponse`).
"""

import re
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from agent.replies import question_for_missing, reply_for_result
from schemas import ChatRequest, ChatResponse, CreateRecord, ListRecords, RecordType
from services import create_record, list_records_for_period

_LIST_INTENT = re.compile(r"\b(что у меня|покажи|какие|план)", re.IGNORECASE)


def _period(text: str, now: datetime) -> tuple[datetime, datetime]:
    """[начало, конец) периода: «завтра», «неделя», по умолчанию — сегодня."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    lowered = text.lower()
    if "завтра" in lowered:
        return today + timedelta(days=1), today + timedelta(days=2)
    if "недел" in lowered:
        return today, today + timedelta(days=7)
    return today, today + timedelta(days=1)


def handle_without_llm(
    db: Session, user_id: UUID, conversation_id: UUID, req: ChatRequest
) -> ChatResponse:
    tz = ZoneInfo(req.timezone)
    now = datetime.now(tz)

    if _LIST_INTENT.search(req.text):
        date_from, date_to = _period(req.text, now)
        result = list_records_for_period(
            db, user_id, ListRecords(date_from=date_from, date_to=date_to)
        )
    else:
        action = CreateRecord(type=RecordType.TASK, title=req.text.strip(), time_given=False)
        result = create_record(db, user_id, action, now=now)

    if not result.ok and result.missing:
        return ChatResponse(
            conversation_id=conversation_id,
            reply=question_for_missing(result.missing),
            result=result,
            awaiting="answer",
        )
    return ChatResponse(
        conversation_id=conversation_id,
        reply=reply_for_result(result, req.timezone),
        result=result,
    )
