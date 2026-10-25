# backend-02a: сервисный слой записей и состояния

**Исполнитель:** Денис

## Цель
Реализовать сервисный слой бизнес-логики (`backend/services/`) для создания записей, выборки дел за период и управления черновиками разговора, изолировав предметную логику от HTTP-маршрутизации и деталей ORM.

## Контекст
- **Стек:** Python 3.13, Pydantic v2, SQLAlchemy 2 (по техническим решениям в `docs/decisions.md`).
- **Зависимость:** Выполняется после [backend-01a](backend-01a-shema-bd.md) (таблицы в базе данных уже созданы).
- **Контрактная изоляция:** Сервисный слой принимает и возвращает **исключительно Pydantic-модели** контрактов: `Record`, `ActionResult`, `ConversationState` ([`docs/contracts/agent-tools.md`](../contracts/agent-tools.md), [`docs/contracts/data-model.md`](../contracts/data-model.md)). Внутренние ORM-объекты SQLAlchemy (`backend/db/models.py`) остаются внутри сервисов и наружу не передаются.
- **Сервисы работы с записями (`backend/services/records.py`):**
  1. `create_record(db, user_id: UUID, action: CreateRecord) -> ActionResult`:
     - **Валидация бизнес-правил:**
       - Дата и время должны содержать часовой пояс (`start.tzinfo is not None`).
       - Для типа `meeting` поле `start` является обязательным. Если оно отсутствует — возвращается понятная ошибка без выброса исключений.
       - Если переданы оба поля `start` и `end`, время окончания должно быть строго позже начала: `end > start`.
       - При создании новой записи дата не должна быть в прошлом.
       - Время не названо (`action.time_given is False`): встреча не сохраняется — результат сообщает, что не хватает времени (`missing` в `ActionResult`), чтобы агент переспросил «На какое время?»; задача и напоминание сохраняются с `all_day = True`. Фиктивной полуночи 00:00 нет.
     - **Результат:**
       - При успехе: запись сохраняется в PostgreSQL, возвращается `ActionResult(action="create_record", ok=True, records=[record])`.
       - При ошибке валидации: возвращается `ActionResult(action="create_record", ok=False, error="описание проблемы")` со статусом ошибки, без падения приложения с 500 ошибкой.
  2. `list_records_for_period(db, user_id: UUID, action: ListRecords) -> ActionResult`:
     - Выбирает записи пользователя, попадающие в интервал `[date_from, date_to]` по началу (`start`) или по сроку (`deadline`): «какие задачи на завтра» находит и задачи, у которых есть только срок.
     - Применяет фильтрацию по списку типов `types`, если они переданы (например, только `['meeting']`).
     - Сортирует записи по времени (начало или срок).
     - Возвращает `ActionResult(action="list_records", ok=True, records=records)`. Если за период ничего не найдено — `records=[]`.
- **Сервисы состояния разговора (`backend/services/conversation.py`):**
  1. `get_or_create_conversation_state(db, conversation_id: UUID, user_id: UUID) -> ConversationState`:
     - Извлекает текущее состояние диалога по `conversation_id`.
     - Если диалог новый — создаёт пустую запись состояния с указанным `user_id` и возвращает её.
  2. `save_conversation_state(db, state: ConversationState) -> None`:
     - Сохраняет обновлённые поля состояния (`focus_record_id`, `pending`, `candidates`, `missing`, `awaiting`) — имена строго из `ConversationState` в контракте в базу данных.
  3. `merge_pending(state: ConversationState, incoming: dict) -> ConversationState`:
     - Сливает новые непустые поля (`val is not None`) из входящего словаря аргументов с уже имеющимся черновиком `state.pending`.
     - Очищает черновик (`pending`, `missing`, `awaiting`) после успешного завершения действия.

### Источники для изучения
- **Паттерн слияния слотов черновика без потерь:** телефонный ассистент [livekit-booking-system](https://github.com/Basit-Arif/livekit-booking-system/blob/93e6e4cf1d8402bf797ec786a5364f5d8e4aa5b6/src/services/context_manager.py) (файл `src/services/context_manager.py`, метод `_save`). Паттерн обновления словаря контекста: `merged = {k: (v if v is not None else old.get(k)) for k, v in incoming.items()}`. Позволяет дописывать новые параметры (например, названное время встречи на втором шаге), не затирая уже сохранённое название дела.
- **Архитектурное разделение слоёв `api / agent / services`:** открытый календарный ассистент [CaliBOT](https://github.com/mallahyari/calibot/tree/44c08c7c1a02c8bd18825abaa13e013a8de53423/backend/app/services) (директория `backend/app/services`). Пример изоляции доменной логики календаря от HTTP-контроллеров FastAPI.

## Критерии готовности
- [ ] Функция `create_record` валидирует правила дат и типов, сохраняет запись в БД и возвращает `ActionResult`.
- [ ] Ошибки валидации (`end < start`, дата в прошлом) возвращают `ActionResult(ok=False, error=...)` без выброса пятисоток.
- [ ] Встреча без названного времени не сохраняется, а результат сообщает, что не хватает времени; задача и напоминание без времени сохраняются «на весь день».
- [ ] Функция `list_records_for_period` возвращает отсортированные по времени записи пользователя за указанный диапазон — по началу и по сроку — с учётом фильтра по типам.
- [ ] Написано 2 быстрых смоук-теста через `pytest` на чистых функциях (без поднятия БД):
  1. Тест слияния словарей в `merge_pending` (проверка, что `title` не затирается, а новый `start` добавляется).
  2. Тест валидации дат в `create_record` (проверка возврата `ok=False` при `end < start`).

## На усмотрение исполнителя
Внутренняя структура файлов сервисного пакета, стратегия управления сессиями (контекстный менеджер или передача явного аргумента `db`).
