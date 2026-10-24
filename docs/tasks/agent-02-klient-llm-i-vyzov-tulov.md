# agent-02: клиент LLM и оркестрация вызова инструментов

**Исполнитель:** Илья

## Цель
Реализовать асинхронный клиент агента на базе официального SDK `openai` с поддержкой передачи пользовательских настроек через `LLMConfig` ([`docs/contracts/api.md`](../contracts/api.md)), принудительным вызовом инструментов (`tool_choice="required"`), парсингом ответа в строгие модели Pydantic и диспетчеризацией в реестр действий `ACTIONS`.

## Контекст
- **Стек:** Python 3.13, `openai>=1.60.0`, Pydantic v2 (по техническим решениям в `docs/decisions.md`).
- **Контрактная основа:** Контракты [`docs/contracts/agent-tools.md`](../contracts/agent-tools.md), [`docs/contracts/api.md`](../contracts/api.md) и принятое техническое решение об одном вызове LLM на реплику (`docs/decisions.md`).
- **Анализ твоей ветки `feature/ilya-agent-skeleton`:**
  - Ветка содержит отличный каркас реестра `ACTIONS` и обработчиков, но требует двух обязательных изменений:
    1. **Универсальный клиент:** Перейди с библиотеки `google-genai` на официальный `openai.AsyncOpenAI`. Все современные провайдеры (Google Gemini, OpenAI, локальные серверы Ollama/vLLM) поддерживают единый OpenAI-совместимый интерфейс.
    2. **Удаление in-memory истории:** Удали локальный словарь `history: dict`. По принятым техническим решениям состояние разговора сохраняется в PostgreSQL через сервисы Дениса ([backend-02a](backend-02a-servisy-zapisej.md)).
- **Универсальная инициализация клиента (`LLMConfig`):**
  - Модель настроек определена в контракте [`docs/contracts/api.md`](../contracts/api.md):
    ```python
    class LLMConfig(BaseModel):
        base_url: str | None = None
        api_key: str | None = None
        model: str | None = None
    ```
  - Логика фабрики клиента:
    - `base_url`: значение из `config.base_url` (если передано клиентом), иначе значение переменной окружения `LLM_BASE_URL`.
    - `api_key`: значение из `config.api_key` (если передано клиентом), иначе значение переменной окружения `LLM_API_KEY`.
    - `model`: имя модели из `config.model` (если передано), иначе переменная окружения `LLM_MODEL`.
    - Никаких захардкоженных условий `if provider == "..."` в коде быть не должно — SDK универсально принимает любой совместимый URL.
- **Вызов модели с принудительными инструментами:**
  - Системный промпт строится генератором Давида (`backend/agent/system_prompt.py::build_compact_system_prompt`).
  - Схемы инструментов передаются из `backend/agent/tools.py::get_agent_tools()` ([agent-01](agent-01-prompty-i-shemy-tools.md)).
  - Параметр вызова `tool_choice="required"` — гарантирует, что LLM вернёт вызов одного из 4 инструментов и не уйдёт в неструктурированный свободный текст.
- **Строгий парсинг ответа:**
  - Из ответа `response.choices[0].message.tool_calls[0]` извлекается имя инструмента и аргументы в JSON.
  - Аргументы десериализуются через Pydantic-модель `LLMAction.model_validate({"action": tool_name, **json.loads(arguments)})`.
  - При ошибке JSON или невалидных полях агент возвращает понятное сообщение пользователю без падения сервера.
- **Реестр действий (`ACTIONS`) и точка входа:**
  - `ACTIONS: dict[str, Callable]` сопоставляет дискриминатор действия с сервисной функцией:
    - `"create_record"` → `services.records.create_record(db, user_id, action)`
    - `"list_records"` → `services.records.list_records_for_period(db, user_id, action)`
    - `"search_records"` → вызов функции поиска (до реализации модуля Родиона — заглушка текстового поиска)
    - `"ask_user"` → формирование ответа с запросом недостающих данных
  - Главная функция агента:
    ```python
    async def process_user_turn(
        db_session,
        user_id: UUID,
        conversation_id: UUID,
        text: str,
        timezone_name: str,
        llm_config: LLMConfig | None = None,
    ) -> ChatResponse: ...
    ```

### Источники для изучения
- **Паттерн вызова OpenAI Tools и разбора аргументов без фреймворков:** проект [agents-from-scratch](https://github.com/langchain-ai/agents-from-scratch/blob/main/src/email_assistant/workflow.py) (файл `src/email_assistant/workflow.py`, функция вызова модели и узел `tool_node`). Посмотри, как чистый Python с Pydantic делает проверку тулов без нагромождения сторонних абстракций.
- **Организация асинхронного агента в связке с FastAPI:** открытый ассистент [CaliBOT](https://github.com/mallahyari/calibot/blob/44c08c7c1a02c8bd18825abaa13e013a8de53423/backend/app/agent/nlp_agent.py) (файл `backend/app/agent/nlp_agent.py`). Пример чистого класса агента с инжекцией настроек и изоляцией обработчиков.

## Критерии готовности
- [ ] Агент инициализирует `AsyncOpenAI` строго на основе параметров `LLMConfig` и переменных окружения `.env` без захардкоженных условий на конкретных провайдеров.
- [ ] Из кода полностью удалён in-memory словарь истории сообщений.
- [ ] Запрос к LLM выполняется с `tool_choice="required"`, ответ всегда строго парсится в модель `LLMAction`.
- [ ] Отрабатывает Сценарий 1 (создание задачи со всеми параметрами): распознавание фразы пользователя, вызов `create_record` и сохранение в PostgreSQL.
- [ ] При таймауте внешнего API возвращается `ChatResponse(reply="Сервис распознавания временно недоступен...", result=None)` со статусом ошибки без 500 исключения.
- [ ] Написан 1 быстрый смоук-тест через `pytest`, проверяющий фабрику клиента и корректное считывание `LLMConfig`.

## На усмотрение исполнителя
Организация таймаутов сетевых запросов (по умолчанию 10–15 секунд), структура вспомогательных классов маппинга сетевых ошибок.
