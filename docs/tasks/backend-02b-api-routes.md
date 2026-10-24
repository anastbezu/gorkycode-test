# backend-02b: маршруты API чата и панели дел

**Исполнитель:** Денис

## Цель
Подключить маршруты FastAPI к реальному сервисному слою и базе данных, поддержать идентификацию пользователя через заголовок `X-User-Id`, приём настроек LLM в запросе чата и обеспечить работу автоматической документации на `/docs`.

## Контекст
- **Стек:** Python 3.13, FastAPI, Pydantic v2 (по техническим решениям в `docs/decisions.md`). Архитектура слоёв: `api / agent / services / db`.
- **Зависимости:** Выполняется после [backend-02a](backend-02a-servisy-zapisej.md) (сервисный слой готов) и [backend-01b](backend-01b-import-dataset.md) (модуль инициализации данных готов).
- **Работа с существующей веткой:**
  - Твоя ветка `feature/backend-03-api-zaglushki` уже содержит структуру приложения FastAPI, настройку CORS, эндпоинты `/health`, `/api/chat` и `/api/items`.
  - Сделай `rebase` этой ветки на свежий `develop`.
  - Замени временные заглушки из `fixtures.py` на вызовы реального сервисного слоя к PostgreSQL.
- **Идентификация пользователя (`docs/decisions.md`):**
  - Пользователь идентифицируется через заголовок запроса `X-User-Id` (UUID браузера).
  - Напиши FastAPI Dependency (`get_current_user_id`), которая:
    1. Считывает заголовок `X-User-Id`.
    2. Если заголовок отсутствует или пуст — генерирует новый `uuid4()` и отдаёт его в заголовке ответа клиенту.
    3. При первом визите нового пользователя инициирует загрузку стартового датасета через `bootstrap_user_data(user_id)`.
- **Эндпоинты API ([`docs/contracts/api.md`](../contracts/api.md)):**
  1. `POST /api/chat`:
     - Принимает тело `ChatRequest`:
       - `conversation_id: UUID | None` (если `None` — создаётся новый разговор).
       - `text: str` (сообщение пользователя).
       - `timezone: str` (IANA-пояс браузера, например `Europe/Moscow`).
       - `llm_config: LLMConfig | None` (пользовательские настройки провайдера, модели и ключа API по `docs/contracts/api.md`).
     - Возвращает `ChatResponse`:
       - `conversation_id: UUID`.
       - `reply: str` (текстовый ответ пользователю).
       - `result: ActionResult | None` (структурированный результат действия для отрисовки на фронтенде).
       - `awaiting: Literal["answer", "choice"] | None` (сигнал ожидания ответа на вопрос или выбора варианта).
     - До интеграции агента Ильи и Давида эндпоинт вызывает сервис `create_record` / `list_records_for_period` через диспетчер и возвращает настоящий ответ из базы данных.
  2. `GET /api/items`:
     - Эндпоинт для боковой панели фронтенда «Мои дела».
     - Принимает параметры фильтрации:
       - `from: datetime | None`
       - `to: datetime | None`
       - `type: RecordType | None`
       - `status: RecordStatus | None`
     - Возвращает список объектов записей `list[Record]` в формате JSON.
  3. `GET /health`:
     - Проверяет подключение к базе данных (`SELECT 1`).
     - Возвращает `{"status": "ok", "db": "connected"}` с кодом 200, либо 503 при недоступности БД.
- **Настройка CORS:**
  - Разреши методы `GET, POST, OPTIONS, PUT, DELETE` и заголовки `Content-Type, X-User-Id, Authorization` для origin-ов локальной разработки (`http://localhost:3000`, `http://localhost:5173`) и продакшн-домена (`https://gorky.bond`).

### Источники для изучения
- **Передача настроек LLM и контекста диалога в теле запроса:** персональный ассистент [Khoj](https://github.com/khoj-ai/khoj/blob/ae229ca894c0b80ad84664afcfdde523b5e87057/src/khoj/utils/rawconfig.py) (файл `src/khoj/utils/rawconfig.py`, класс `ChatRequestBody`). Обрати внимание на паттерн передачи динамических параметров LLM (ключ, модель) от клиента: сервер не сохраняет секреты пользователя в базу, а передаёт их в оперативную сессию обращения к модели.
- **Внедрение зависимостей для заголовков в FastAPI:** официальное руководство [FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/). Паттерн создания функции-зависимости с `Header(default=None)` для прозрачного извлечения `X-User-Id` во всех маршрутах API.

## Критерии готовности
- [ ] Эндпоинт `POST /api/chat` принимает `ChatRequest` (включая `llm_config`), отдаёт валидный `ChatResponse`, присваивает `conversation_id` новым диалогам.
- [ ] Пользователь изолируется через `X-User-Id`; новому пользователю автоматически генерируется UUID и загружаются стартовые данные.
- [ ] Эндпоинт `GET /api/items` отдаёт реальные записи из базы с учётом фильтров по датам и типам.
- [ ] Эндпоинт `GET /health` корректно проверяет статус подключения к PostgreSQL.
- [ ] CORS настроен и пропускает запросы от фронтенда (`localhost` и `https://gorky.bond`).
- [ ] Автоматическая документация OpenAPI генерируется и доступна на `http://localhost:8000/docs`.
- [ ] Написан 1 смоук-тест через `pytest` и `httpx.AsyncClient`, проверяющий код 200 на эндпоинте `/health`.

## На усмотрение исполнителя
Организация роутеров по отдельным файлам (`chat.py`, `items.py`, `health.py`), способ передачи `X-User-Id` (заголовок или cookie в качестве запасного варианта).
