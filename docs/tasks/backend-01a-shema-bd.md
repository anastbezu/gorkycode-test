# backend-01a: схема базы данных и миграции Alembic

**Исполнитель:** Денис

## Цель
Развернуть схему PostgreSQL через миграции Alembic для хранения записей пользователей и состояния разговоров по контрактам репозитория, обеспечив изоляцию данных пользователей и повторяемую инициализацию базы данных с нуля.

## Контекст
- **Стек:** Python 3.13, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3, PostgreSQL + pgvector (по техническим решениям в `docs/decisions.md`). Контейнер базы данных описан в `docker-compose.yaml`.
- **Контрактная изоляция:** Внешний мир (агент, API) общается с хранилищем **исключительно через Pydantic-схемы** из `backend/schemas/` ([`docs/contracts/data-model.md`](../contracts/data-model.md)). Внутренние ORM-модели SQLAlchemy (`backend/db/models.py`) наружу не экспортируются и не импортируются другими модулями.
- **Работа с существующими ветками:**
  - Возьми наработки из своих веток `feature/backend-01-shema-bd` и `feature/backend-02-pydantic-schemas`.
  - В модели `backend/db/models.py::Record` **удали** поле `embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))` и константу `EMBEDDING_DIM = 1536`. Модель векторных представлений выбирается отдельно; векторную колонку и расширение для смыслового поиска Родион добавит в модуле поиска.
- **Таблица `records`:**
  - Поля:
    - `id: UUID` (первичный ключ, `uuid4`).
    - `user_id: UUID` (индексированный идентификатор пользователя для изоляции данных).
    - `type: str` (значения: `'task'`, `'meeting'`, `'reminder'`).
    - `title: str` (суть дела без мусорных слов).
    - `start: timestamptz | None` (дата и время начала со смещением).
    - `end: timestamptz | None` (дата и время окончания со смещением).
    - `all_day: bool` (флаг дела на весь день, если время не названо).
    - `deadline: timestamptz | None` (крайний срок со смещением).
    - `status: str` (значения: `'active'`, `'done'`, `'cancelled'`).
    - `created_at: timestamptz` (время создания записи).
    - `updated_at: timestamptz` (время последнего обновления записи).
  - Индексы: составной индекс `(user_id, start)` и индекс `(user_id, status)` для быстрых выборок списков.
- **Таблица `conversation_states`:**
  - Поля:
    - `conversation_id: UUID` (первичный ключ).
    - `user_id: UUID` (индексированный идентификатор пользователя).
    - `focus_record_id: UUID | None` (идентификатор последней затронутой записи).
    - `pending_action: JSONB | None` (черновик незавершённого действия при слот-филлинге).
    - `missing: JSONB | None` (список имён недостающих полей, например `["start"]`).
    - `awaiting: str | None` (режим ожидания: `'answer'`, `'choice'` или `None`).
    - `updated_at: timestamptz` (время последнего обновления состояния).
- **Миграции Alembic (`alembic/`):**
  - Настрой окружение Alembic (`env.py`), связав его с `Base.metadata` и URL подключения к базе данных из настроек приложения.
  - Первая миграция активирует расширение pgvector: `CREATE EXTENSION IF NOT EXISTS vector;`.
  - Вторая миграция создаёт таблицы `records` и `conversation_states` со всеми индексами и ограничениями.
  - Команда `alembic upgrade head` должна успешно отрабатывать на чистой базе без ошибок.

### Источники для изучения
- **Модель напоминаний с временными поясами и флагом `all_day`:** репозиторий [OpenVoiceOS Alerts](https://github.com/OpenVoiceOS/ovos-skill-alerts/blob/29d82d2e02080618aa54b0d58b18e499a531d3a3/util/alert.py) (файл `util/alert.py`, класс `Alert`). Обрати внимание, как модель нормализует смещение пояса и отделяет дела с точным временем от дел на весь день (`all_day`), исключая фиктивное время полуночи (00:00).
- **Структура контекста диалога отдельными полями состояния:** телефонный ассистент [livekit-booking-system](https://github.com/Basit-Arif/livekit-booking-system/blob/93e6e4cf1d8402bf797ec786a5364f5d8e4aa5b6/src/services/redis_service.py) (файл `src/services/redis_service.py`, модель `BookingContext`). Паттерн показывает хранение состояния разговора в виде структурированных полей (`pending_action`, `missing`), а не простыни сырых текстовых сообщений. У нас этот паттерн хранится в PostgreSQL в таблице `conversation_states`.

## Критерии готовности
- [ ] Схема базы данных создаётся повторяемо с нуля командой `alembic upgrade head`.
- [ ] В таблице `records` отсутствуют поля `embedding` и `EMBEDDING_DIM`.
- [ ] Таблица `conversation_states` создана и поддерживает сохранение черновиков (`pending_action`, `missing`, `focus_record_id`).
- [ ] Все временные поля имеют тип с часовым поясом (`timestamptz`). Запись без часового пояса отклоняется.
- [ ] Данные одного `user_id` изолированы от других пользователей.
- [ ] Написан 1 смоук-тест через `pytest`, проверяющий создание и чтение тестовой записи в БД.
- [ ] Описание схемы базы данных зафиксировано в `docs/modules/backend.md`.

## На усмотрение исполнителя
Именование внешних ключей и индексов, организация фабрики сессий БД, выбор синхронного драйвера `psycopg` или асинхронного `asyncpg` для сессий.
