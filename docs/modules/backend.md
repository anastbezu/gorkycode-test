# Модуль backend: хранилище

Владелец: Денис. Контракт данных — [`docs/contracts/data-model.md`](../contracts/data-model.md).

## Устройство

```
backend/
├── schemas/          Pydantic-модели из docs/contracts/ — единственное, что видят агент, API и поиск
├── db/
│   ├── models.py     ORM-модели SQLAlchemy 2 (только для сервисов бэкенда, наружу не отдаются)
│   └── session.py    движок и сессии, адрес из DATABASE_URL
├── alembic/          миграции схемы
└── tests/            pytest
```

Граница: сервисы читают строки `db.models.*` и отдают наружу `schemas.Record` /
`schemas.ConversationState` через `Model.model_validate(row)` (`from_attributes=True`).

## Схема базы

### `records` — задачи, встречи, напоминания

| Колонка | Тип | Правила |
|---|---|---|
| `id` | uuid | PK, `uuid4` |
| `user_id` | uuid | NOT NULL, анонимный id браузера |
| `type` | varchar(16) | `task` / `meeting` / `reminder` |
| `title` | text | не пустой |
| `start_at` | timestamptz | обязателен у `meeting` |
| `end_at` | timestamptz | позже `start_at` |
| `all_day` | boolean | default `false`; дата без времени — `true`, а не полночь |
| `deadline` | timestamptz | срок задачи, не начало |
| `status` | varchar(16) | `active` / `done` / `cancelled`, default `active` |
| `created_at`, `updated_at` | timestamptz | `now()`; `updated_at` обновляется при изменении |

Индексы: `(user_id, start_at)` — списки за период; `(user_id, status)` — активные / выполненные.

### `conversation_states` — состояние разговора

| Колонка | Тип | Смысл |
|---|---|---|
| `conversation_id` | uuid | PK |
| `user_id` | uuid | индекс |
| `focus_record_id` | uuid | FK → `records.id`, `ON DELETE SET NULL`; «её», «эту встречу» |
| `pending` | jsonb | черновик действия агента (`LLMAction`) при уточнении |
| `candidates` | uuid[] | записи, из которых пользователь выбирает |
| `missing` | text[] | каких полей не хватает, напр. `{start}` |
| `awaiting` | varchar(16) | `answer` / `choice` / NULL |
| `updated_at` | timestamptz | время последнего изменения |

## Принятые решения

- **`start_at` / `end_at` в БД, `start` / `end` в Python.** `end` — зарезервированное слово SQL:
  в сыром SQL (поиск) его пришлось бы всегда брать в кавычки. Атрибуты ORM и поля Pydantic
  называются как в контракте, переименование видно только в SQL.
- **Время только с часовым поясом.** Все даты — `timestamptz` (Postgres хранит их в UTC).
  Тип `AwareDateTime` отклоняет `datetime` без пояса ещё до запроса: иначе Postgres молча
  приписал бы ему пояс сервера.
- **Enum — `varchar` + `CHECK`**, а не нативный тип Postgres: новые значения добавляются
  обычной миграцией. Правила контракта (у встречи есть начало, конец позже начала) продублированы
  в `CHECK` — база не примет некорректную запись даже в обход сервисов.
- **Изоляция пользователей** — на уровне запросов: каждый запрос сервисов фильтрует по `user_id`,
  оба индекса начинаются с `user_id`.
- **Синхронный psycopg 3** (`postgresql+psycopg://`): проще код и тесты, FastAPI выполняет
  синхронные эндпоинты в пуле потоков. Psycopg 3 умеет и async, если понадобится.
- **Векторов в `records` нет.** Модель эмбеддингов ещё не выбрана; колонку и индекс добавит
  модуль поиска отдельной миграцией. Расширение `vector` включает миграция `0001`.

## Миграции

```bash
cd backend
uv run alembic upgrade head          # создать / обновить схему
uv run alembic downgrade base        # откатить всё
uv run alembic check                 # модели совпадают с базой?
uv run alembic revision --autogenerate -m "что изменилось"   # новая миграция после правки models.py
```

| Ревизия | Что делает |
|---|---|
| `0001` | `CREATE EXTENSION IF NOT EXISTS vector` |
| `0002` | таблицы `records`, `conversation_states`, индексы и ограничения |

Автогенерированную миграцию нужно вычитать: в ней не должно быть ссылок на код приложения
(`db.models...`), имена ограничений оборачиваются в `op.f(...)`.

## Локальный запуск и тесты

```bash
docker compose up -d postgres        # из корня репозитория
cd backend
# DATABASE_URL в .env: внутри Docker хост `postgres`, с хоста — `localhost`
#   DATABASE_URL=postgresql://postgres:postgres_password@localhost:5432/hackathon_db
uv run alembic upgrade head
uv run pytest
```

Тесты с базой берут `TEST_DATABASE_URL` (или `DATABASE_URL`), сами накатывают миграции и
работают в откатываемой транзакции. Без доступной базы они пропускаются.
