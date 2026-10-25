# Агент

## Подготовка запроса

`process_user_turn` получает IANA-пояс браузера из `ChatRequest.timezone`,
создаёт один aware `now` в этом поясе и использует его на весь запрос:

```python
now = datetime.now(ZoneInfo(timezone_name))
prompt = build_compact_system_prompt(now, timezone_name)
tools = localize_tools(get_agent_tools(), now)
```

`build_compact_system_prompt` находится в `agent/system_prompt.py`,
`get_agent_tools` и `localize_tools` — в `agent/tools.py`.

Промпт содержит 14 строк: роль, один инструмент, время, пояс,
даты всех дней двух недель и общие правила. Отсчёт недель выполняется
после перевода времени в пояс пользователя, начало недели — понедельник.
Модель не получает инструкции о втором ходе после исполнения инструмента.

## Схемы и локализация

Единый источник моделей — `backend/schemas/actions.py`.
`get_agent_tools()` экспортирует CreateRecord, ListRecords, SearchRecords,
AskUser в формат OpenAI Chat Completions Tools. `$defs` и `$ref` сохраняются.
Модели импортируются из `schemas`, копий Pydantic-моделей в агенте нет.

Описания дат в исходных `Field(description=...)` должны содержать
`{ISO_EXAMPLE}`. `localize_tools(tools, now)` делает глубокую копию и заменяет
этот маркер только в строках `description`, включая вложенные `$defs`.
Используется `str.replace`, остальные фигурные скобки не интерпретируются.
Пример — 15:00 локальной даты `now` с вычисленным смещением её пояса.
Базовые схемы и результаты других запросов не изменяются.

## Дата без явно названного времени

Согласованная интерпретация: если назван день, `start` содержит локальное
начало этого дня и `time_given=false`. Это техническое представление даты,
а не заявленное пользователем время. Для задачи сервис выставляет all_day.
`start=null` означает, что дата вообще не названа.
Для встречи без времени сервис возвращает `missing=["start"]`, агент
уточняет время. Если нехватка известна при выборе действия, доступен ask_user.
Срок «до конца недели» хранится в deadline: воскресенье 23:59:59.
Сигнал all_day формирует сервис, в CreateRecord нового поля нет.

## Исполнение и ответ

Один вызов LLM выбирает действие. Код исполняет его, проверяет результат и
формирует ответ по шаблонам ActionResult: успех, ошибка, отсутствие результатов,
missing и выбор кандидата. Обработчик missing сохраняет pending-состояние.
Второй вызов LLM в рамках той же реплики не требуется.
Вызов SDK, исполнение и хранение состояния реализует владелец каркаса агента.

## Клиент LLM

`agent/llm.py::make_client(llm_config)` создаёт `AsyncOpenAI` и возвращает
его вместе с именем модели. Каждое поле берётся из `LLMConfig` запроса,
а если там пусто — из окружения: `base_url` ← `LLM_BASE_URL`,
`api_key` ← `LLM_API_KEY`, `model` ← `LLM_MODEL`. Условий на конкретного
провайдера в коде нет. Пустой `LLM_BASE_URL` означает адрес OpenAI
по умолчанию. Таймаут — 15 секунд, один повтор.
Нет ключа или модели — `LLMConfigError`.

## Вызов и разбор действия

`get_action(text, now, timezone_name, llm_config)` делает один вызов
`chat.completions.create`: системный промпт и пользовательская фраза,
четыре локализованных инструмента, `tool_choice="required"`.
Из `tool_calls[0]` берутся имя инструмента и JSON-аргументы и проверяются
через `LLMAction.model_validate({"action": name, **args})`. Нет вызова
инструмента, битый JSON или поля не проходят схему — `ActionParseError`.

## Реестр действий

`agent/actions.py::ACTIONS` сопоставляет `action` с обработчиком
`(db, user_id, action) -> ActionResult`; `execute` выбирает обработчик по
`action.action`, для неизвестного действия возвращает `ok=False` с ошибкой.
`ask_user` в реестр не входит: `process_user_turn` сразу возвращает
`AskUser.question` с `awaiting="answer"`.

Пока сервисы записей и поиск не готовы, обработчики — заглушки с `TODO`:
`create_record` собирает `Record` без сохранения (встреча без времени —
`missing=["start"]`), `list_records` и `search_records` возвращают пустой
список.

## Ошибки

`process_user_turn` не пробрасывает ошибки LLM наружу, пользователь
получает `ChatResponse` с понятным `reply` и `result=None`:

| Ошибка | Ответ |
|---|---|
| `LLMConfigError` — нет ключа или модели | ассистент не настроен, задать ключ и модель |
| `openai.APIError` — таймаут, сеть, лимиты, 5xx | сервис распознавания временно недоступен |
| `ActionParseError` | не удалось разобрать запрос |

## Шаблоны ответа

`agent/replies.py` строит `reply` из `ActionResult` без второго вызова LLM:
`missing` → вопрос о недостающем поле (`awaiting="answer"`), ошибка →
`error`, созданная запись → «Готово: «название» на дд.мм в чч:мм» во времени
пользователя, список и поиск → число записей или «ничего нет».

## Проверки

Тесты написаны на pytest. Запуск из `backend/`:

```bash
uv run pytest
uv run ruff check
```

`backend/tests/test_agent_prompt_tools.py`: календарь двух недель и пояс,
изоляция локализации, JSON CreateRecord и экспорт четырёх инструментов,
пример со смещением пользователя во всех полях дат после `localize_tools`.
`backend/tests/test_llm_client.py`: `LLMConfig` и окружение, нет ключа,
пустой `LLM_BASE_URL`.
`backend/tests/test_process_user_turn.py`: таймаут API, неразобранное
действие, нет ключа или модели, встреча без времени. Сети в тестах нет.
