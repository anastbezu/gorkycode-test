from google.genai import types
from datetime import datetime, timezone
from uuid import uuid4

from .models import ActionResult, ListRecords, Record, RecordType

list_records_decl = types.FunctionDeclaration(
    name="list_records",
    description=(
        "Показать задачи, встречи и напоминания за указанный период. "
        "Вызывай, когда пользователь спрашивает, что у него запланировано: "
        "«что у меня сегодня», «какие встречи завтра», «что на этой неделе». "
        "Не вызывай для поиска старой записи по смыслу («найди задачу про договор»), "
        "для этого есть search_records. Не вызывай для создания записей."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "date_from": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Начало периода, включительно. Формат ISO 8601 с часовым поясом, "
                    "например 2026-10-24T00:00:00+03:00."
                ),
            ),
            "date_to": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Конец периода, НЕ включительно. Формат ISO 8601 с часовым поясом. "
                    "Для одного дня это начало следующего дня: "
                    "для 24 октября date_to = 2026-10-25T00:00:00+03:00."
                ),
            ),
            "types": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING, enum=["task", "meeting", "reminder"]),
                description=(
                    "Необязательно. Какие типы записей показать: task (задача), "
                    "meeting (встреча), reminder (напоминание). "
                    "Укажи, только если пользователь спросил про конкретный тип "
                    "(«какие встречи...»). Если спросил «что у меня», не заполняй."
                ),
            ),
        },
        required=["date_from", "date_to"],
    )
)


def handle_list_records(user_id, action: ListRecords) -> ActionResult:
    # TODO: replace with call to Denis's service
    fake = Record(
        id=uuid4(),
        user_id=uuid4(),
        type=RecordType.MEETING,
        title="Встреча с командой",
        start=action.date_from,
        created_at=datetime.now(timezone.utc),
    )
    return ActionResult(action="list_records", ok=True, records=[fake])


TOOLS_CONFIG = types.GenerateContentConfig(
    tools=[types.Tool(function_declarations=[list_records_decl])],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)

ACTIONS = {
    "list_records": (ListRecords, handle_list_records),
}
