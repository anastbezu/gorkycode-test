LIST_RECORDS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_records",
        "description": (
            "Показать задачи, встречи и напоминания за указанный период. "
            "Вызывай, когда пользователь спрашивает, что у него запланировано: "
            "«что у меня сегодня», «какие встречи завтра», «что на этой неделе». "
            "Не вызывай для поиска старой записи по смыслу («найди задачу про договор»), "
            "для этого есть search_records. Не вызывай для создания записей."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": (
                    "Начало периода, включительно. Формат ISO 8601 с часовым поясом, "
                    "например 2026-10-24T00:00:00+03:00."
                )},
                "date_to": {"type": "string", "description": (
                    "Конец периода, НЕ включительно. Формат ISO 8601 с часовым поясом. "
                    "Для одного дня это начало следующего дня: "
                    "для 24 октября date_to = 2026-10-25T00:00:00+03:00."
                )},
                "types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["task", "meeting", "reminder"]},
                    "description": (
                        "Необязательно. Какие типы записей показать: task (задача), "
                        "meeting (встреча), reminder (напоминание). "
                        "Укажи, только если пользователь спросил про конкретный тип "
                        "(«какие встречи...»). Если спросил «что у меня», не заполняй."
                    ),
                },
            },
            "required": ["date_from", "date_to"],
        },
    },
}

CREATE_RECORD_TOOL = {
    "type": "function",
    "function": {
        "name": "create_record",
        "description": "Создать задачу, встречу или напоминание: когда просят что-то запланировать, поставить или напомнить.",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["task", "meeting", "reminder"]},
                "title": {"type": "string", "description": "Суть без даты и времени: «позвонить Ивану»"},
                "start": {"type": "string",
                          "description": "Начало, ISO 8601 со смещением, например 2026-10-26T15:00:00+03:00. Не указывай, если время не названо."},
                "deadline": {"type": "string", "description": "Срок, ISO 8601 со смещением («до конца недели»)."},
                "time_given": {"type": "boolean", "description": "Пользователь назвал время, а не только дату."},
            },
            "required": ["type", "title", "time_given"],
        },
    },
}

ASK_USER_TOOL = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": "Задать вопрос, если для действия не хватает данных (например, не названо время встречи).",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "missing": {"type": "array", "items": {"type": "string"},
                            "description": "Каких полей не хватает: start, type"},
            },
            "required": ["question", "missing"],
        },
    },
}

TOOLS = [LIST_RECORDS_TOOL, CREATE_RECORD_TOOL, ASK_USER_TOOL]  # TODO: заменить схемами из agent-01 (Давид)
