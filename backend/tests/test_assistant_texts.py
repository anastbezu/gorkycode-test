"""Тексты ответа по `docs/assistant-texts.md` (agent-11).

Эталоны раздела 12 — на фиксированном «сейчас» (среда, 21.10.2026, 10:00) и записях
стартового набора; каждый ответ ещё и проходит правила раздела 13 (`check_reply`).
Без базы и модели: шаблоны получают готовые записи и результаты.
"""

import re
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agent.change_replies import reply_for_change
from agent.changes import ChangeOutcome
from agent.list_replies import reply_for_list
from agent.replies import (
    ASK_DAY_AND_TIME,
    ASK_TIME,
    MODEL_DOWN,
    NOT_CONFIGURED,
    NOT_PARSED,
    REFUSED_CHOICE,
    REFUSED_DRAFT,
    draft_reminder,
    question_for_missing,
    reply_for_result,
)
from agent.search_replies import reply_for_search
from agent.targets import NO_TARGET
from schemas import (
    ActionResult,
    CreateRecord,
    Help,
    ListRecords,
    Record,
    RecordStatus,
    SearchFilters,
    SetStatus,
    TargetRef,
    UndoLast,
    UpdateRecord,
)

TZ = "Europe/Moscow"
MSK = ZoneInfo(TZ)
NOW = datetime(2026, 10, 21, 10, 0, tzinfo=MSK)


def at(day: str, time: str = "00:00") -> datetime:
    return datetime.fromisoformat(f"{day}T{time}").replace(tzinfo=MSK)


def rec(title: str, start: datetime | None = None, *, kind: str = "task",
        end: datetime | None = None, deadline: datetime | None = None,
        all_day: bool = False, status: str = "active") -> Record:
    return Record(id=uuid4(), user_id=uuid4(), type=kind, title=title, start=start, end=end,
                  deadline=deadline, all_day=all_day, status=status, created_at=NOW)


def meeting(title: str, start: datetime, **kw) -> Record:
    return rec(title, start, kind="meeting", **kw)


def day(start: str, days: int = 1, types=None) -> ListRecords:
    first = at(start)
    return ListRecords(date_from=first, date_to=first + timedelta(days=days), types=types)


# --- правила раздела 13 ---------------------------------------------------------------------

DATE = re.compile(r"\b\d{1,2}\.\d{2}(\.\d{4})?\b")
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
MARKDOWN = re.compile(r"[*#_`]|^\s*(- |\d+\))", re.M)
INTRO = ("Конечно", "С удовольствием", "Разумеется", "Отличный вопрос")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-")
LIMITS = {"confirm": 20, "warning": 35, "many": 45, "question": 12, "choice": 20,
          "list": 45, "error": 25, "help": 35}


def words(text: str) -> int:
    return len([w for w in text.split() if w not in {"—", "–", "-"}])


def check_reply(text: str, kind: str, awaiting: str | None = None) -> None:
    """Правила раздела 13 документа: то, что проверяется без знания записи."""
    assert not DATE.search(text), f"дата цифрами: {text}"
    assert not EMOJI.search(text), text
    assert not MARKDOWN.search(text), f"markdown или значок списка: {text}"
    assert not text.startswith(INTRO), text
    assert text.count("?") <= 1, f"больше одного вопроса: {text}"
    if awaiting is None:
        assert "?" not in text, f"вопрос без ожидания ответа: {text}"
    assert words(text) <= LIMITS[kind], f"{words(text)} слов > {LIMITS[kind]}: {text}"
    if kind == "error":
        assert ("ничего не сохранено" in text.lower() or "не создана" in text
                or "не удалось сохранить" in text.lower()), text
    assert not UUID.search(text), text
    assert "Озвучка" not in text and "Текст:" not in text


def created(record: Record, conflicts: list[Record] | None = None) -> str:
    result = ActionResult(action="create_record", ok=True, records=[record],
                          conflicts=conflicts or [])
    return reply_for_result(result, TZ, now=NOW)


# --- создание (раздел 5) --------------------------------------------------------------------

CREATED = [
    ("1.1", rec("позвонить Ивану", at("2026-10-22", "10:00"), kind="reminder"),
     "Напомню завтра, 22 октября, в 10:00: позвонить Ивану."),
    ("1.2", rec("Отправить отчёт", at("2026-10-23"), all_day=True),
     "Добавил задачу «Отправить отчёт» на послезавтра, 23 октября."),
    ("1.3", rec("Купить билеты", deadline=at("2026-10-25", "23:59")),
     "Добавил задачу «Купить билеты» со сроком до воскресенья, 25 октября."),
    ("1.4", meeting("встреча с командой", at("2026-10-22", "15:00")),
     "Добавил в календарь: встреча с командой, завтра, 22 октября, в 15:00."),
    ("2.3", rec("Отправить смету Анне", at("2026-10-26"), all_day=True),
     "Добавил задачу «Отправить смету Анне» на понедельник, 26 октября."),
    ("2.5", rec("проверить сроки по сайту", at("2026-10-21", "12:00"), kind="reminder"),
     "Напомню сегодня в 12:00: проверить сроки по сайту."),
    ("2.12", rec("поздравить команду", at("2026-12-31", "12:00"), kind="reminder"),
     "Напомню 31 декабря, в 12:00: поздравить команду."),
    ("2.12а", rec("Купить молоко", kind="reminder"),
     "Добавил напоминание «Купить молоко» без даты."),
    ("2.12б", rec("Подготовить акт", deadline=at("2026-11-01", "23:59")),
     "Добавил задачу «Подготовить акт» со сроком до 1 ноября."),
    ("2.12в", rec("Разобрать почту", at("2026-10-24"), all_day=True),
     "Добавил задачу «Разобрать почту» на субботу, 24 октября."),
    ("2.12г", rec("Сдать отчёт", at("2026-10-31"), all_day=True),
     "Добавил задачу «Сдать отчёт» на 31 октября."),
    ("2.20", meeting("созвон с Марией", at("2026-10-28", "13:15")),
     "Добавил в календарь: созвон с Марией, 28 октября, в 13:15."),
    ("2.22", meeting("встреча с Иваном и Ольгой по бюджету", at("2026-10-22", "17:00"),
                     end=at("2026-10-22", "18:30")),
     "Добавил в календарь: встреча с Иваном и Ольгой по бюджету, завтра, 22 октября, "
     "с 17:00 до 18:30."),
    ("3.12", rec("Подготовить смету"), "Добавил задачу «Подготовить смету» без даты."),
    ("5.1 усл.", rec("Созвониться с банком", at("2026-10-22", "15:30")),
     "Добавил задачу «Созвониться с банком» на завтра, 22 октября, в 15:30."),
    ("6.4", rec("про договор", at("2026-10-26"), kind="reminder", all_day=True),
     "Напомню в понедельник, 26 октября, в течение дня: про договор."),
    ("6.15", rec("Отправить смету Анне", deadline=at("2026-10-22", "23:59")),
     "Добавил задачу «Отправить смету Анне» со сроком до завтра, 22 октября."),
]


@pytest.mark.parametrize(("case", "record", "expected"), CREATED, ids=[c[0] for c in CREATED])
def test_creation_confirms_with_type_and_spoken_date(case, record, expected) -> None:
    reply = created(record)
    assert reply == expected
    check_reply(reply, "confirm")


def test_conflict_and_duplicate_8_7_8_8() -> None:
    alfa = meeting("Созвон с Альфой по бюджету", at("2026-10-22", "12:00"))
    reply = created(meeting("встреча с Анной", at("2026-10-22", "12:30")), [alfa])
    assert reply == ("Добавил в календарь: встреча с Анной, завтра, 22 октября, в 12:30. "
                     "Пересекается с «Созвон с Альфой по бюджету» (завтра в 12:00).")
    check_reply(reply, "warning")

    duplicate = ActionResult(action="create_record", ok=False, records=[alfa],
                             error="Такая запись уже есть — второй раз не создаю.")
    reply = reply_for_result(duplicate, TZ, now=NOW)
    assert reply == ("Такая запись уже есть: «Созвон с Альфой по бюджету» — завтра, "
                     "22 октября, в 12:00. Новую не создавал.")
    check_reply(reply, "warning")


@pytest.mark.parametrize(("action", "expected"), [
    (CreateRecord(type="meeting", title="встреча с Ольгой", start=at("2026-10-21", "09:00"),
                  time_given=True),
     "Сегодня в 09:00 уже прошло, запись не создана. Назовите другое время."),
    (CreateRecord(type="reminder", title="позвонить Ивану", start=at("2026-10-20"),
                  time_given=False),
     "Вчера уже прошло, запись не создана. Назовите другую дату."),
    (CreateRecord(type="reminder", title="позвонить в банк", start=at("2026-10-20", "10:00"),
                  time_given=True),
     "Вчера в 10:00 уже прошло, запись не создана. Назовите другое время."),
])
def test_past_date_3_10_8_3_8_4(action, expected) -> None:
    result = ActionResult(action="create_record", ok=False,
                          error="Дата (start) уже в прошлом — нельзя поставить запись.")
    reply = reply_for_result(result, TZ, action=action, now=NOW)
    assert reply == expected
    check_reply(reply, "error")


# --- вопросы, отказ, справка, ошибки (разделы 5.4, 6, 10, 11) --------------------------------

def test_questions_and_draft_reminder_6_2_6_3() -> None:
    with_day = CreateRecord(type="meeting", title="Встреча с Иваном", start=at("2026-10-22"),
                            time_given=False)
    no_day = CreateRecord(type="meeting", title="Встреча с Дмитрием", time_given=False)
    assert question_for_missing(["start"], with_day) == ASK_TIME
    assert question_for_missing(["start"], no_day) == ASK_DAY_AND_TIME
    for question in (ASK_TIME, ASK_DAY_AND_TIME):
        check_reply(question, "question", awaiting="answer")

    reminder = draft_reminder("Встреча с Иваном", ["start"], with_day)
    reply = ("На завтра одно дело: 09:15 — подготовить вопросы для Максимом. " + reminder)
    assert reminder == "Запись «Встреча с Иваном» так и не создана — на какое время?"
    check_reply(reply, "many", awaiting="time")


def test_refusal_help_and_errors() -> None:
    for text in (REFUSED_DRAFT, REFUSED_CHOICE):
        check_reply(text, "confirm")
    assert REFUSED_DRAFT == "Хорошо, ничего не записал."
    help_reply = reply_for_result(ActionResult(action="help", ok=True), TZ,
                                  action=Help(kind="help"), now=NOW)
    offtopic = reply_for_result(ActionResult(action="help", ok=True), TZ,
                                action=Help(kind="offtopic"), now=NOW)
    assert help_reply.startswith("Я помогаю вести задачи, встречи и напоминания. Например:")
    assert offtopic.startswith("С этим не помогу: я веду задачи, встречи и напоминания.")
    for text in (help_reply, offtopic):
        check_reply(text, "help")
    for text in (NOT_CONFIGURED, MODEL_DOWN, NOT_PARSED):
        check_reply(text, "error")
    assert "распознавания" not in MODEL_DOWN  # речь уже распознана (И-02)


# --- списки (раздел 8) ----------------------------------------------------------------------

MARIA = meeting("Встреча с Марией по презентации", at("2026-10-21", "08:00"))
PULSE = rec("Подготовиться к встрече с Пульсом", at("2026-10-21", "10:15"))
BUDGET = rec("Обсудить бюджет по презентации", at("2026-10-20", "18:00"))
MAXIM = rec("Подготовить вопросы для Максимом", at("2026-10-22", "09:15"))
SMETA = rec("Проверить смету по мобильному приложению", at("2026-10-24", "10:45"))
ELENA = rec("Отправить протокол Еленой", at("2026-10-24", "14:15"))
INTEGR = meeting("Встреча с Марией по интеграции", at("2026-10-24", "20:45"))
MATERIALS = rec("Обновить материалы по презентации", at("2026-10-25", "13:15"))
WEEK = [BUDGET, MARIA, PULSE, MAXIM, SMETA, ELENA, INTEGR, MATERIALS]
TASKS = ["task", "reminder"]

LISTS = [
    ("1.6", [MARIA, PULSE], day("2026-10-21"),
     "На сегодня 2 дела: 08:00 — встреча с Марией по презентации; "
     "10:15 — подготовиться к встрече с Пульсом."),
    ("1.8", [MARIA], day("2026-10-21", types=["meeting"]),
     "На сегодня одна встреча: 08:00 — встреча с Марией по презентации."),
    ("1.11", WEEK, day("2026-10-19", 7),
     "На этой неделе — 8 дел. Первые по времени: вчера в 18:00 — обсудить бюджет по "
     "презентации; сегодня в 08:00 — встреча с Марией по презентации; сегодня в 10:15 — "
     "подготовиться к встрече с Пульсом. Остальные на экране."),
    ("4.1", [MAXIM], day("2026-10-22"),
     "На завтра одно дело: 09:15 — подготовить вопросы для Максимом."),
    ("4.3", [MARIA, INTEGR], day("2026-10-19", 7, types=["meeting"]),
     "На этой неделе — 2 встречи: сегодня в 08:00 — встреча с Марией по презентации; "
     "в субботу в 20:45 — встреча с Марией по интеграции."),
    ("4.4", [PULSE, MAXIM, SMETA, ELENA, MATERIALS], day("2026-10-21", 5, types=TASKS),
     "До 25 октября — 5 дел. Первые по времени: сегодня в 10:15 — подготовиться к встрече "
     "с Пульсом; завтра в 09:15 — подготовить вопросы для Максимом; в субботу в 10:45 — "
     "проверить смету по мобильному приложению. Остальные на экране."),
    ("4.6", [], day("2026-10-23", types=["reminder"]), "На послезавтра напоминаний нет."),
    ("4.8", [SMETA, ELENA, INTEGR, MATERIALS], day("2026-10-24", 2),
     "На выходных — 4 дела. Первые по времени: в субботу в 10:45 — проверить смету по "
     "мобильному приложению; в субботу в 14:15 — отправить протокол Еленой; в субботу "
     "в 20:45 — встреча с Марией по интеграции. Остальные на экране."),
    ("4.9", [BUDGET], day("2026-10-20"),
     "Вчера — одно дело: 18:00 — обсудить бюджет по презентации."),
    ("4.10", [rec("Провести планёрку по интеграции", at("2026-12-31", "20:00"))],
     day("2026-12-31"), "На 31 декабря одно дело: 20:00 — провести планёрку по интеграции."),
    ("4.11", [], day("2026-10-31"), "На 31 октября ничего не запланировано."),
    ("4.18", [], ListRecords(date_from=at("2026-10-21", "18:00"), date_to=at("2026-10-22")),
     "На сегодня с 18:00 ничего не запланировано."),
]


@pytest.mark.parametrize(("case", "records", "action", "expected"), LISTS,
                         ids=[c[0] for c in LISTS])
def test_list_replies_section_12(case, records, action, expected) -> None:
    reply = reply_for_list(records, action, TZ, NOW)
    assert reply == expected
    check_reply(reply, "list")


def test_next_week_is_named_by_dates_4_5() -> None:
    records = [rec("Проверить коммерческое предложение", at("2026-10-26", "16:45")),
               rec("Проверить акт по аналитике", at("2026-10-26", "20:30")),
               rec("Передать отчёт на согласование", at("2026-10-29", "15:30")),
               rec("Подготовить акт", at("2026-11-01", "17:45"))]
    reply = reply_for_list(records, day("2026-10-26", 7), TZ, NOW)
    assert reply.startswith("На следующей неделе — 4 дела. Первые по времени: в понедельник "
                            "в 16:45 — проверить коммерческое предложение;")
    assert "29 октября, в 15:30 — передать отчёт" in reply
    check_reply(reply, "list")


# --- поиск (раздел 9) -----------------------------------------------------------------------

def search(records, query, filters=None, similar=False) -> str:
    reply = reply_for_search(records, query, TZ, NOW, similar=similar, filters=filters)
    check_reply(reply, "list")
    return reply


def test_search_section_12() -> None:
    hackathon = meeting("Встреча с Марией по хакатону", at("2024-10-30", "08:30"))
    assert search([hackathon], "встреча с Марией по хакатону") == (
        "«Встреча с Марией по хакатону» — 30 октября 2024 года, в 08:30.")

    ivan = [meeting("Встреча с Иваном по CRM", at("2025-04-04", "18:00")),
            meeting("Встреча с Иваном по презентации", at("2025-09-27", "15:45")),
            meeting("Встреча с Иваном по презентации", at("2026-03-05", "15:45"))]
    assert search(ivan, "встреча с Иваном") == (
        "Нашёл 3 встречи. Последняя — 5 марта, в 15:45: «Встреча с Иваном по презентации».")

    sever = [meeting(f"Созвон с Севером по {tail}", at(d, t)) for tail, d, t in [
        ("новому продукту", "2024-01-22", "11:30"), ("бюджету", "2024-09-22", "10:00"),
        ("презентации", "2024-11-24", "08:45"), ("интеграции", "2025-04-18", "16:45"),
        ("интеграции", "2025-06-18", "18:30"), ("интеграции", "2025-11-27", "10:00"),
        ("CRM", "2026-08-22", "08:30")]]
    assert search(sever, "созвон с Севером") == (
        "Нашёл 7 встреч. Последняя — 22 августа, в 08:30: «Созвон с Севером по CRM».")

    demo = [meeting("Демо проекта по мобильному приложению", at(d, "12:00"))
            for d in ["2024-04-16", "2025-01-15", "2025-06-19", "2025-08-31", "2025-10-06",
                      "2026-03-27", "2026-04-11"]]
    demo.append(meeting("Демо проекта по мобильному приложению", at("2027-01-05", "20:15")))
    assert search(demo, "демо мобильное приложение") == (
        "«Демо проекта по мобильному приложению» — 8 раз. Ближайшая — 5 января 2027 года, "
        "в 20:15.")

    calls = [rec("Позвонить Дмитрием", at(d, t)) for d, t in [
        ("2024-02-04", "17:00"), ("2025-01-04", "14:15"), ("2025-03-30", "11:30"),
        ("2025-06-21", "10:45"), ("2026-03-04", "19:00"), ("2026-06-09", "10:45")]]
    assert search(calls, "звонил Дмитрию") == (
        "«Позвонить Дмитрием» — 6 раз. Последняя — 9 июня, в 10:45.")

    assert search([], "аквапарк") == (
        "По запросу «аквапарк» ничего не нашлось. Попробуйте другие слова.")
    last_week = SearchFilters(date_from=at("2026-10-12"), date_to=at("2026-10-19"))
    assert search([], "планёрка по CRM", last_week) == (
        "На прошлой неделе по запросу «планёрка по CRM» ничего не нашлось. "
        "Попробуйте другой период или другие слова.")

    orbit = meeting("Созвон с Орбитой по презентации", at("2026-10-29", "15:30"))
    assert search([orbit], "созвон с Орбитой по хакатону", similar=True) == (
        "Точно не нашёл «созвон с Орбитой по хакатону». Похожие: «Созвон с Орбитой по "
        "презентации» — 29 октября, в 15:30.")


# --- изменение, статус, откат, выбор (раздел 7) ----------------------------------------------

def changed(outcome: ChangeOutcome, action, shown: int = 0) -> str:
    return reply_for_change(outcome, action, TZ, NOW, shown_count=shown)


DESIGNER = meeting("Встреча с дизайнером", at("2026-10-22", "11:00"))


def test_change_replies_section_12() -> None:
    ivan = meeting("Встреча с Иваном", at("2026-10-23", "15:00"))
    move = UpdateRecord(target=TargetRef(text="встречу с Иваном"), start=ivan.start)
    reply = changed(ChangeOutcome(ActionResult(action="update_record", ok=True,
                                               records=[ivan])), move)
    assert reply == "Перенёс «Встреча с Иваном»: теперь послезавтра, 23 октября, в 15:00."
    check_reply(reply, "confirm")

    olga = rec("Позвонить Ольге", status="done")
    done = SetStatus(target=TargetRef(text="Ольге"), status=RecordStatus.DONE)
    reply = changed(ChangeOutcome(ActionResult(action="set_status", ok=True,
                                               records=[olga])), done)
    assert reply == "Отметил как выполненное: «Позвонить Ольге»."

    cancel = SetStatus(target=TargetRef(text="дизайнер"), status=RecordStatus.CANCELLED)
    reply = changed(ChangeOutcome(ActionResult(action="set_status", ok=True,
                                               records=[DESIGNER])), cancel)
    assert reply == ("Отменил «Встреча с дизайнером» — завтра, 22 октября, в 11:00. "
                     "Чтобы вернуть, скажите «верни».")
    check_reply(reply, "warning")

    reply = changed(ChangeOutcome(ActionResult(action="undo_last", ok=True,
                                               restored=[DESIGNER])), UndoLast())
    assert reply == "Вернул «Встреча с дизайнером» — завтра, 22 октября, в 11:00."

    vector = [meeting("Созвон с Вектором по CRM", at("2025-04-30", "19:45")),
              meeting("Созвон с Вектором по сайту", at("2027-12-14", "19:00")),
              meeting("Созвон с Вектором по интеграции", at("2026-10-22", "15:00"))]
    reply = changed(ChangeOutcome(ActionResult(action="set_status", ok=False,
                                               candidates=vector)), cancel)
    assert reply == "Нашёл 3 встречи. Какую именно?"
    check_reply(reply, "choice", awaiting="choice")

    site = vector[1]
    reply = changed(ChangeOutcome(ActionResult(action="set_status", ok=True, records=[site],
                                               restored=[vector[2]])), cancel)
    assert reply == ("Вернул «Созвон с Вектором по интеграции» — завтра, 22 октября, в 15:00. "
                     "Отменил «Созвон с Вектором по сайту» — 14 декабря 2027 года, в 19:00. "
                     "Чтобы вернуть, скажите «верни».")


def test_mass_cancel_confirm_and_done_7_19_7_22() -> None:
    week = SearchFilters(date_from=at("2026-10-19"), date_to=at("2026-10-26"))
    mass = SetStatus(target=TargetRef(all=True, text="созвон", filters=week),
                     status=RecordStatus.CANCELLED)
    calls = [meeting("Созвон с Альфой по бюджету", at("2026-10-22", "12:00")),
             meeting("Созвон с Вектором по интеграции", at("2026-10-22", "15:00"))]
    outcome = ChangeOutcome(ActionResult(action="set_status", ok=False, candidates=calls),
                            confirm=True)
    reply = changed(outcome, mass)
    assert reply == ("Нашёл 2 встречи: завтра в 12:00 — созвон с Альфой по бюджету; "
                     "завтра в 15:00 — созвон с Вектором по интеграции. Отменить все?")
    check_reply(reply, "many", awaiting="confirm")

    tomorrow = SearchFilters(date_from=at("2026-10-22"), date_to=at("2026-10-23"))
    everything = [MAXIM, rec("Позвонить Ивану", at("2026-10-22", "10:00"), kind="reminder"),
                  DESIGNER, calls[0], calls[1]]
    ask = SetStatus(target=TargetRef(all=True, filters=tomorrow), status=RecordStatus.CANCELLED)
    reply = changed(ChangeOutcome(ActionResult(action="set_status", ok=False,
                                               candidates=everything), confirm=True), ask)
    assert reply == ("Нашёл 5 записей: 09:15 — подготовить вопросы для Максимом; 10:00 — "
                     "позвонить Ивану; 11:00 — встреча с дизайнером. Остальные на экране. "
                     "Отменить все?")
    check_reply(reply, "many", awaiting="confirm")

    reply = changed(ChangeOutcome(ActionResult(action="set_status", ok=True,
                                               records=everything)), ask)
    assert reply == ("Отменил 5 записей: «Подготовить вопросы для Максимом»; «Позвонить "
                     "Ивану»; «Встреча с дизайнером». Остальные на экране. Чтобы вернуть, "
                     "скажите «верни».")
    check_reply(reply, "many")

    done = ask.model_copy(update={"status": RecordStatus.DONE})
    reply = changed(ChangeOutcome(ActionResult(action="set_status", ok=False,
                                               candidates=calls), confirm=True), done)
    assert reply.endswith("Отметить все выполненными?")


def test_no_target_and_similar_6_2_7() -> None:
    mark = SetStatus(target=TargetRef(focus=True), status=RecordStatus.DONE)
    reply = changed(ChangeOutcome(ActionResult(action="set_status", ok=False,
                                               error=NO_TARGET)), mark)
    assert reply == "Не понял, какую запись отметить. Назовите её."
    move = UpdateRecord(target=TargetRef(focus=True), start=at("2026-10-22", "10:00"))
    reply = changed(ChangeOutcome(ActionResult(action="update_record", ok=False,
                                               error=NO_TARGET)), move, shown=3)
    assert reply == "Не понял, какую запись перенести. Назовите номер из списка."
    check_reply(reply, "question")

    orbit = meeting("Созвон с Орбитой по презентации", at("2026-10-29", "15:30"))
    reply = changed(ChangeOutcome(ActionResult(action="update_record", ok=False,
                                               candidates=[orbit]), similar=True), move)
    assert reply == ("Точно такой нет. Может, «Созвон с Орбитой по презентации» — "
                     "29 октября, в 15:30?")
    check_reply(reply, "choice", awaiting="choice")
