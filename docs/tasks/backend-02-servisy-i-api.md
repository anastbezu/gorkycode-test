# backend-02: сервисы записей и API чата

**Исполнитель:** Денис

## Цель
Реализовать сервисный слой бизнес-логики для создания и выборки записей, подключить эндпоинты FastAPI к базе данных, поддержать приём пользовательских настроек LLM в запросе чата и обеспечить работоспособность API с автодокументацией на `/docs`.

## Контекст
- **Стек:** Python 3.13, FastAPI, Pydantic v2. Архитектура слоёв: `api / agent / services / db` (`docs/decisions.md`).
- **Зависимость:** Выполняется после завершения [backend-01](backend-01-hranenie.md) (хранилище и миграции уже готовы).
- **Контрактная изоляция:** Сервисы работают только с моделями контрактов `Record` и `ActionResult` ([`docs/contracts/agent-tools.md`](../contracts/agent-tools.md)). Внутренние ORM-объекты базы данных наружу не просачиваются.
- **Работа с уже начатой веткой:**
  - Твоя ветка `feature/backend-03-api-zaglushki` уже содержит каркас FastAPI, CORS, `/health`, мок `/api/chat` и эндпоинт `/api/items`.
  - После сдачи и мержа `backend-01` сделай `rebase` ветки `backend-03` на свежий `develop`.
  - Замени in-memory фикстуры (`fixtures.py`) на вызовы реального сервисного слоя к PostgreSQL.
- **Сервисный слой (`backend/services/`):**
  - `create_record(user_id: UUID, action: CreateRecord) -> ActionResult`: валидация дат, проверка обязательных полей (для встречи — время начала), сохранение в БД, возврат созданной записи. Если валидация не прошла — возвращается `ActionResult(ok=False, error="текст ошибки")`, без выброса пятисоток.
  - `list_records_for_period(user_id: UUID, action: ListRecords) -> ActionResult`: выборка записей пользователя за период `[date_from, date_to)` с фильтрацией по типам, сортировка по времени.
  - `get_or_create_conversation_state(conversation_id: UUID, user_id: UUID) -> ConversationState` и `save_conversation_state(...)`.
- **API эндпоинты ([`docs/contracts/api.md`](../contracts/api.md)):**
  - `POST /api/chat`: принимает `ChatRequest` (включая опциональный `llm_config: LLMConfig | None` по `docs/decisions.md`), возвращает `ChatResponse`. Идентификация пользователя — через заголовок `X-User-Id` (UUID) по `docs/decisions.md`.
  - До интеграции полноценного агента Ильи/Давида эндпоинт `/api/chat` использует временную логику диспетчеризации (из твоей ветки 03), но вызывает настоящие сервисы и сохраняет данные в БД.
  - `GET /api/items`: эндпоинт для боковой панели «Мои дела», фильтры по `from`, `to`, `type`, поддержка часового пояса.
- **Поиск по смыслу:** Метод `search()` реализуется модулем Родиона отдельной задачей; в сервисах создания записей генерация эмбеддингов пока не вызывается.

### Источники для изучения
- Раскладка слоёв `api / agent / services`: CaliBOT (открытый голосовой календарный бот), репозиторий [backend/app](https://github.com/mallahyari/calibot/tree/44c08c7c1a02c8bd18825abaa13e013a8de53423/backend/app) — чистая изоляция маршрутов FastAPI и сервисов.
- Проверки в сервисном слое и возврат понятной ошибки в структуре ответа: телефонный ассистент livekit-booking, файл [src/services/clinic_service.py](https://github.com/Basit-Arif/livekit-booking-system/blob/93e6e4cf1d8402bf797ec786a5364f5d8e4aa5b6/src/services/clinic_service.py).
- Структура запроса чата с `conversation_id` и `timezone`: персональный ассистент Khoj, класс `ChatRequestBody` в [src/khoj/utils/rawconfig.py](https://github.com/khoj-ai/khoj/blob/ae229ca894c0b80ad84664afcfdde523b5e87057/src/khoj/utils/rawconfig.py).

## Критерии готовности
- [ ] Сервис `create_record` валидирует данные и сохраняет запись в БД; при невалидных данных возвращает `ActionResult(ok=False, error=...)`.
- [ ] Сервис `list_records_for_period` возвращает записи пользователя, отсортированные по времени.
- [ ] Эндпоинт `POST /api/chat` принимает `ChatRequest` (включая `llm_config`), отдаёт `ChatResponse`, присваивает `conversation_id` новым диалогам.
- [ ] Эндпоинт `GET /api/items` возвращает записи для панели дел с корректной фильтрацией.
- [ ] Автоматическая документация OpenAPI доступна и корректно отображается на `http://localhost:8000/docs`.
- [ ] Юнит-тесты на сервисы и API проходят (`pytest`).
- [ ] Архитектура сервисов описана в `docs/modules/backend.md`.

## На усмотрение исполнителя
Внутренняя раскладка сервисных функций по файлам, организация транзакций базы данных, формат вспомогательных фикстур для тестов.
