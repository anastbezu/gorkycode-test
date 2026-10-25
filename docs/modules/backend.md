# Модуль backend: хранилище

Владелец: Денис. Контракт данных — [`docs/contracts/data-model.md`](../contracts/data-model.md).

## Устройство

```
backend/
├── schemas/          Pydantic-модели из docs/contracts/ — единственное, что видят агент, API и поиск
├── db/
│   ├── models.py     ORM-модели SQLAlchemy 2 (только для сервисов бэкенда, наружу не отдаются)
│   └── session.py    движок и сессии, адрес из DATABASE_URL
├── services/         бизнес-логика: записи (records.py) и состояние разговора (conversation.py)
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

## Сервисы

Чистая бизнес-логика без HTTP: её вызывают агент (tools) и API. Принимают и возвращают только
Pydantic-модели контрактов. Сессия БД передаётся явным аргументом `db` первым параметром.
Ошибки бизнес-правил — `ActionResult(ok=False, error=...)`, не исключения: агент передаёт текст
ошибки LLM, API не отдаёт 500.

### Записи — `services/records.py`

**`create_record(db, user_id, action: CreateRecord) -> ActionResult`**

Проверки по порядку (`validate_create`, до обращения к базе):

| Правило | Результат |
|---|---|
| у `start` / `end` / `deadline` нет часового пояса | `ok=False` |
| встреча без `start` | `ok=False`, `missing=["start"]` |
| встреча, время не названо (`time_given=False`) | не сохраняется, `ok=False`, `missing=["start"]` — агент переспросит «На какое время?» |
| `end <= start` | `ok=False` |
| `start` или `deadline` в прошлом | `ok=False` |

- `all_day=True` — только если назван день, но не время (`start` задан, `time_given=False`):
  задача и напоминание «на весь день». Задача без даты («прочитать книгу») или только со сроком —
  `all_day=False`.
- «В прошлом» для `all_day` сравнивается по дням в поясе самой даты: «сегодня» без времени —
  не прошлое. Для записей со временем — `start < now − 1 минута` (`PAST_GRACE`): LLM считает
  время от момента запроса, проверка идёт после ответа модели, и «напомни через минуту»
  не должно отклоняться из-за этих секунд.
- При успехе: `ok=True`, `records=[созданная запись]`.

**`list_records_for_period(db, user_id, action: ListRecords) -> ActionResult`**

- Записи пользователя, у которых `start` **или** `deadline` в `[date_from, date_to)` — правая
  граница не включается (контракт `agent-tools.md`): «сегодня» — до 00:00 завтра, и запись
  «на весь день» завтра в него не попадает. «Задачи на завтра» находят и задачи только со сроком.
- Отменённые (`cancelled`) не показываются; остальные статусы — показываются.
- Фильтр `types`, если передан. Сортировка по `coalesce(start, deadline)`.
- Ничего нет — `ok=True, records=[]`.

### Состояние разговора — `services/conversation.py`

| Функция | Что делает |
|---|---|
| `get_conversation_state(db, conversation_id, user_id)` | состояние существующего разговора, без создания: нет разговора → `None`. Чужой разговор → `ConversationAccessError` |
| `get_or_create_conversation_state(db, conversation_id, user_id)` | состояние из БД; для нового разговора создаёт пустое. Чужой разговор → `ConversationAccessError` |
| `save_conversation_state(db, state)` | сохраняет `focus_record_id`, `pending`, `candidates`, `missing`, `awaiting` |
| `merge_pending(state, incoming)` | дописывает в черновик `pending` непустые поля из `incoming`, уже сохранённое не затирает; заполненные поля убирает из `missing` |
| `clear_pending(state)` | очищает `pending`, `missing`, `awaiting` после успешного действия |

Сценарий уточнения: «поставь встречу с Иваном завтра» → `create_record` вернул `missing=["start"]` →
агент кладёт черновик в `pending`, `awaiting="answer"`, сохраняет → «в 14» →
`merge_pending(state, {"start": ..., "time_given": True})` → `create_record(pending)` →
`clear_pending` + `focus_record_id` = созданная запись → сохранить.

`merge_pending` — по паттерну livekit-booking-system (`context_manager._save`): берётся весь старый
черновик и поверх кладутся только непустые новые значения. Очистка вынесена в отдельную
`clear_pending`: в одном вызове слить и сразу очистить черновик нельзя.

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

## Стартовый датасет — `services/bootstrap.py`

Новый пользователь при первом визите получает копию 1000 записей из
`backend/data/voice_assistant_events_1000.csv` (`docs/decisions.md`, «Датасет»), чтобы списки
за период и поиск можно было показать сразу.

**`bootstrap_user_data(db_session, user_id, timezone_str) -> int`** — возвращает число
добавленных записей (0, если у пользователя записи уже есть). Неизвестный пояс —
`ZoneInfoNotFoundError`, некорректное имя (пустое, с `..`) — `ValueError`, оба до обращения к базе.

**Транзакция.** Функция сама завершает транзакцию переданной сессии: `commit` и когда загрузила,
и когда пропустила; при ошибке — `rollback` и исключение дальше. Поэтому вызывать её первой в
запросе, до своих изменений, — дальше сессией можно пользоваться как обычно.

| Правило | Как сделано |
|---|---|
| Часовой пояс | время из CSV — локальное время пользователя: «10:00» остаётся 10:00 в его поясе (`datetime.combine(date, time, tzinfo=ZoneInfo(tz))`), в базе — `timestamptz` |
| Тип | `detect_type(text)`: «Напомнить …» → `reminder`; первое слово «Встреча» / «Созвон» / «Демо» / «Планёрка» или «планёрк…» в любом месте («Провести планёрку …») → `meeting`; остальное → `task`. «Отправить итоги встречи …», «Подготовиться к встрече …» — `task`: «встреча» не первое слово |
| Статус | событие раньше момента импорта → `done`, иначе `active` |
| Поля | дата и время CSV → `start`, `all_day = false` (время в CSV есть всегда), `deadline` пустой |
| Идемпотентность | есть хоть одна запись у `user_id` → импорт пропускается |
| Изоляция | все записи — строго переданному `user_id` |
| Скорость | один запрос `INSERT … VALUES (…), (…)` на все строки (SQLAlchemy `insert(Record).values([...])`), ~0,5 с на 1000 записей |

**Одновременные первые запросы.** Два запроса нового пользователя могут прийти одновременно
(чат и панель «Мои дела»). Чтобы датасет не загрузился дважды, импорт берёт транзакционную
блокировку Postgres по `user_id` (`pg_advisory_xact_lock`) — второй запрос ждёт первого и видит,
что записи уже есть. Блокировка снимается с концом транзакции — в том числе при ошибке импорта.
Оба случая проверяют тесты: 4 одновременных импорта одному пользователю → данные загружены один
раз; битый CSV → исключение, записей нет, блокировка свободна.

Распределение типов в датасете: `task` 761, `meeting` 186, `reminder` 53 (тест на полном CSV).
Дубли текста (376 уникальных на 1000 строк) — разные события с разными датами, загружаются все.

### Ручная загрузка (CLI)

```bash
# из корня репозитория — как в постановке
uv run --project backend python -m backend.scripts.load_dataset --user-id <UUID>
# или из backend/
uv run python -m scripts.load_dataset --user-id <UUID> --timezone Asia/Yekaterinburg
```

Без `--user-id` создаётся новый UUID; `--timezone` по умолчанию `Europe/Moscow`.

## API — `api/`, `main.py`

Маршруты FastAPI поверх сервисов; бизнес-логики в `api/` нет. Swagger — `/docs`.
Запуск: `cd backend && uv run uvicorn main:app --reload`.

| Файл | Что внутри |
|---|---|
| `main.py` | приложение FastAPI, CORS, подключение роутеров |
| `api/deps.py` | пользователь из `X-User-Id`, разбор часового пояса, стартовый датасет новому пользователю |
| `api/chat.py` | `POST /api/chat` |
| `api/items.py` | `GET /api/items` |
| `api/health.py` | `GET /health` |
| `api/dispatch.py` | временный диспетчер чата без LLM — до agent-05 |

### Пользователь — заголовок `X-User-Id`

- Фронтенд хранит UUID в localStorage и присылает его в заголовке `X-User-Id` каждого запроса.
- Нет заголовка или он пустой → сервер выдаёт новый `uuid4()` и возвращает его
  **в заголовке ответа `X-User-Id`** (CORS открывает его фронтенду через `expose_headers`).
- Заголовок есть, но это не UUID → **400**: ошибка клиента, сервер не подменяет id молча.
- Новому пользователю сразу загружается стартовый датасет (`bootstrap_user_data`). Импорт
  вызывается из маршрута, а не из зависимости: ему нужен часовой пояс, а он приходит в теле
  `/api/chat` и в параметре `tz` у `/api/items`.
- Импорт — после проверок запроса (пояс, период, разговор). В ответе с ошибкой заголовка
  `X-User-Id` нет, и загруженные до проверки записи остались бы без владельца.
- **Известное ограничение:** «новый пользователь» — тот, кто пришёл без `X-User-Id`. Таблицы
  пользователей нет, поэтому корректный UUID без записей (например, после пересоздания базы)
  датасет не получает — у такого пользователя пусто.

### `POST /api/chat`

Тело — `ChatRequest`, ответ — `ChatResponse` (`docs/contracts/api.md`).

- `conversation_id = null` → новый разговор, сервер присваивает id и создаёт состояние разговора.
- Чужой или несуществующий `conversation_id` → **404**: разговоры создаёт только сервер.
- Неизвестный или пустой `timezone` → **422** с понятным текстом.
- `llm_config` принимается и нигде не сохраняется и не логируется.
- Сервисы синхронные — вызываются через `asyncio.to_thread` (`docs/decisions.md`).

**Временный диспетчер (`api/dispatch.py`)** — пока агент не подключён (agent-05), реплика
разбирается простыми правилами и сразу идёт в настоящие сервисы:
«что у меня…», «покажи…», «какие…», «план…» → список за сегодня / завтра / неделю; остальное →
задача без даты с текстом реплики. Тексты ответов — из `agent/replies.py`, как у агента.
**agent-05:** в `api/chat.py` заменить вызов `handle_without_llm` на
`process_user_turn(db, user.id, conversation_id, req.text, req.timezone, req.llm_config)`
(помечено `TODO(agent-05)`), после этого `api/dispatch.py` можно удалить.

### `GET /api/items`

| Параметр | Смысл |
|---|---|
| `from`, `to` | **обязательные**: период `[from, to)`, ISO 8601 со смещением (`+` в URL кодируется как `%2B`). Обязательны, как `date_from` / `date_to` у `ListRecords` в контракте; без них — 422 |
| `type` | фильтр, можно несколько: `?type=meeting&type=task` |
| `tz` | IANA-пояс пользователя (по умолчанию Europe/Moscow): даты в ответе — в этом поясе |
| `include_undated` | `true` — добавить в конец активные записи **без даты** (блок «Без срока», FEATURES P1 №14). По умолчанию `false` |

Ответ — `list[Record]`, по времени. Записи без даты (с `include_undated=true`) — в конце, у них
`start` и `deadline` пустые: по этому фронтенд отделяет их в свой блок. Фильтр `type` действует
и на них; выполненные и отменённые без даты не показываются (`services.list_undated_records`).

Нет `from` / `to`, `to <= from`, дата без пояса, неизвестный или пустой `tz` → 422.

### `GET /health`

`SELECT 1` в базе: `{"status": "ok", "db": "connected"}` (200) или
`{"status": "error", "db": "unavailable"}` (503) — в том числе когда не задан `DATABASE_URL`.
Таймаут подключения к базе — 5 с (`db/session.py`): недоступная база даёт 503, а не зависание.

### CORS

Разрешены `https://gorky.bond`, `https://www.gorky.bond`, `http://localhost:3000`,
`http://localhost:5173` (и те же с `127.0.0.1`). Переопределяется переменной окружения
`CORS_ORIGINS` (через запятую) без изменения кода.
