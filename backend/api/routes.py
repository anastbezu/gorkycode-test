"""REST API. Сейчас — заглушки с фиксированными ответами (DECOMPOSITION 6.4).

Пользователь — анонимный id браузера в заголовке `X-User-Id` (UUID).
Фронт генерирует его один раз и хранит в localStorage. Без заголовка — демо-пользователь.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query
from pydantic import AwareDatetime

from schemas import ActionResult, ChatRequest, ChatResponse, Record, RecordType

from .fixtures import DEMO_USER_ID, _at, demo_records, user_tz

router = APIRouter()


@router.get("/health", tags=["service"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/chat", response_model=ChatResponse, tags=["chat"])
def chat(
    req: ChatRequest,
    x_user_id: UUID | None = Header(default=None),
) -> ChatResponse:
    """ЗАГЛУШКА. Отвечает по ключевым словам, чтобы фронт мог проверить все состояния:

    - «что у меня…», «покажи», «план» → список за период
    - «найди», «когда» → поиск
    - «встреч» без цифр → уточняющий вопрос (`awaiting = "answer"`)
    - всё остальное → создание задачи
    """
    user_id = x_user_id or DEMO_USER_ID
    conversation_id = req.conversation_id or uuid4()
    text = req.text.lower()
    records = demo_records(user_id, req.timezone)

    if any(w in text for w in ("что у меня", "покажи", "план")):
        result = ActionResult(action="list_records", ok=True, records=records[:4])
        reply = "На ближайшие дни у вас 2 встречи, напоминание и задача."
        awaiting = None
    elif any(w in text for w in ("найди", "когда")):
        result = ActionResult(action="search_records", ok=True, records=[records[-1]])
        reply = "Нашёл задачу «Отправить договор Ивану», она уже выполнена."
        awaiting = None
    elif "встреч" in text and not any(ch.isdigit() for ch in text):
        result = ActionResult(action="ask_user", ok=False, missing=["start"])
        reply = "На какое время поставить встречу?"
        awaiting = "answer"
    else:
        tz = user_tz(req.timezone)
        created = Record(
            id=uuid4(),
            user_id=user_id,
            type=RecordType.TASK,
            title=req.text.strip() or "Новая задача",
            start=_at(tz, 1, 10),
            created_at=datetime.now(timezone.utc),
        )
        result = ActionResult(action="create_record", ok=True, records=[created])
        reply = f"Готово, поставил задачу «{created.title}» на завтра в 10:00."
        awaiting = None

    return ChatResponse(
        conversation_id=conversation_id, reply=reply, result=result, awaiting=awaiting
    )


@router.get("/api/items", response_model=list[Record], tags=["items"])
def list_items(
    date_from: AwareDatetime | None = Query(default=None, alias="from"),
    date_to: AwareDatetime | None = Query(default=None, alias="to"),
    type: list[RecordType] | None = Query(default=None),
    tz: str | None = Query(default=None, description="IANA-пояс, напр. Europe/Moscow"),
    x_user_id: UUID | None = Header(default=None),
) -> list[Record]:
    """ЗАГЛУШКА. Записи для панели «Мои дела». Фильтры по типу и периоду уже работают
    на фиксированных данных; записи без даты попадают в выдачу всегда.

    Пример: `/api/items?from=2026-10-24T00:00:00%2B03:00&to=2026-10-31T00:00:00%2B03:00&type=meeting`
    """
    records = demo_records(x_user_id or DEMO_USER_ID, tz)
    if type:
        records = [r for r in records if r.type in type]

    def in_period(r: Record) -> bool:
        when = r.start or r.deadline
        if when is None:
            return True
        if date_from and when < date_from:
            return False
        if date_to and when >= date_to:
            return False
        return True

    records = [r for r in records if in_period(r)]
    far_future = datetime.now(timezone.utc) + timedelta(days=3650)
    return sorted(records, key=lambda r: r.start or r.deadline or far_future)
