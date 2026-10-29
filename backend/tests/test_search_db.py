"""`search()` и `find_target()` на PostgreSQL: правила контракта docs/contracts/search.md.

Модель эмбеддингов подменена кодировщиком по понятиям: тесты проверяют правила (уровни,
фильтры, порядок, сужение по времени, кэш векторов), а не качество модели — его проверяет
test_search_quality.py на настоящей модели.
"""

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from db import models
from db.models import EMBEDDING_DIM
from schemas import RecordStatus, RecordType, SearchFilters
from search import core, embeddings, find_target, search, vectors

MSK = ZoneInfo("Europe/Moscow")

# Понятие → номер измерения. Текст получает 1 в измерениях понятий, которые в нём есть;
# у текста без понятий — своё измерение, он ни на что не похож.
CONCEPTS = ["звон", "дизайн", "смет", "договор", "север", "дмитри", "иван", "продукт"]
UNRELATED = EMBEDDING_DIM - 1


def concept_vectors(texts: list[str]) -> np.ndarray:
    out = np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)
    for i, text in enumerate(texts):
        low = text.lower()
        dims = [d for d, c in enumerate(CONCEPTS) if c in low] or [UNRELATED]
        out[i, dims] = 1.0
    return out / np.linalg.norm(out, axis=1, keepdims=True)


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    calls = {"documents": 0}

    def embed_documents(texts):
        calls["documents"] += len(texts)
        return concept_vectors(texts)

    monkeypatch.setattr(embeddings, "embed_documents", embed_documents)
    monkeypatch.setattr(embeddings, "embed_queries", concept_vectors)
    return calls


def at(day: int, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=MSK)


def add(db, user_id, title, start=None, *, type=RecordType.TASK, status=RecordStatus.ACTIVE,
        deadline=None, all_day=False):
    row = models.Record(user_id=user_id, type=type, title=title, start=start, deadline=deadline,
                        status=status, all_day=all_day)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def user(db):
    return uuid4()


# ---------- search() ----------

def test_exact_hits_only_newest_first_undated_last(db, user):
    old = add(db, user, "Согласовать смету с Максимом", at(1))
    new = add(db, user, "Отправить смету Ивану", at(20))
    undated = add(db, user, "Проверить смету")
    add(db, user, "Подписать договор", at(5))  # не про смету — не в «точно»

    hits = search(db, user, "смета", SearchFilters())

    assert [h.record.id for h in hits] == [new.id, old.id, undated.id]
    assert {h.match for h in hits} == {"exact"}


def test_levels_do_not_mix_when_exact_found(db, user):
    add(db, user, "Позвонить Дмитрием", at(1))  # по смыслу близко к «звонок»
    exact = add(db, user, "Звонок по договору", at(2))

    hits = search(db, user, "звонок", SearchFilters())

    assert [h.record.id for h in hits] == [exact.id]
    assert hits[0].match == "exact"


def test_similar_when_no_exact_and_nothing_below_threshold(db, user):
    call = add(db, user, "Позвонить Дмитрием", at(3))
    add(db, user, "Купить молоко", at(4))  # ни на что не похоже

    hits = search(db, user, "звонок Дмитрию", SearchFilters())

    assert [h.record.id for h in hits] == [call.id]
    assert hits[0].match == "similar"
    assert hits[0].score >= core.SIMILAR_MIN_SCORE


def test_nothing_found_is_empty(db, user):
    add(db, user, "Купить молоко", at(4))
    assert search(db, user, "встреча с дизайнером", SearchFilters()) == []


def test_filters_apply_before_text(db, user):
    meeting = add(db, user, "Созвон с Севером", at(10), type=RecordType.MEETING)
    add(db, user, "Подготовить отчёт для Севера", at(10))  # задача — отсеет тип
    add(db, user, "Созвон с Севером", at(25), type=RecordType.MEETING)  # вне периода
    add(db, user, "Созвон с Севером", at(11), type=RecordType.MEETING,
        status=RecordStatus.CANCELLED)  # отменённые без фильтра статуса не ищутся

    hits = search(db, user, "Север", SearchFilters(
        types=[RecordType.MEETING], date_from=at(1, 0), date_to=at(20, 0)))

    assert [h.record.id for h in hits] == [meeting.id]


def test_explicit_status_filter_finds_cancelled(db, user):
    cancelled = add(db, user, "Созвон с Севером", at(11), status=RecordStatus.CANCELLED)
    hits = search(db, user, "Север", SearchFilters(status=[RecordStatus.CANCELLED]))
    assert [h.record.id for h in hits] == [cancelled.id]


def test_period_uses_deadline_when_no_start(db, user):
    due = add(db, user, "Сдать смету", deadline=at(15, 23, 59))
    hits = search(db, user, "смета", SearchFilters(date_from=at(15, 0), date_to=at(16, 0)))
    assert [h.record.id for h in hits] == [due.id]


def test_limit_keeps_newest_exact(db, user):
    rows = [add(db, user, "Позвонить Ивану", at(d)) for d in range(1, 6)]
    hits = search(db, user, "позвонить Ивану", SearchFilters(), limit=2)
    assert [h.record.id for h in hits] == [rows[4].id, rows[3].id]


def test_limit_keeps_closest_similar_shown_by_date(db, user):
    close = add(db, user, "Позвонить Дмитрием", at(1))
    add(db, user, "Позвонить Севером по продукту", at(9))  # «звон» есть, «дмитри» нет — дальше
    hits = search(db, user, "звонок Дмитрию", SearchFilters(), limit=1)
    assert [h.record.id for h in hits] == [close.id]


def test_other_users_records_are_never_found(db, user):
    add(db, uuid4(), "Согласовать смету с Максимом", at(1))
    add(db, uuid4(), "Позвонить Дмитрием", at(1))
    assert search(db, user, "смета", SearchFilters()) == []
    assert search(db, user, "звонок Дмитрию", SearchFilters()) == []


# ---------- векторы ----------

def test_vectors_are_per_text_and_computed_once(db, user, fake_model):
    other = uuid4()
    for u in (user, other):
        add(db, u, "Позвонить Дмитрием", at(1))
        add(db, u, "Позвонить Дмитрием", at(2))  # тот же текст — тот же вектор

    search(db, user, "звонок Дмитрию", SearchFilters())
    assert fake_model["documents"] == 1

    search(db, other, "звонок Дмитрию", SearchFilters())  # другой пользователь, тот же текст
    assert fake_model["documents"] == 1
    assert vectors.ensure_vectors(db, ["Позвонить Дмитрием"]) == 0


def test_exact_level_does_not_touch_model(db, user, fake_model):
    add(db, user, "Согласовать смету с Максимом", at(1))
    search(db, user, "смета", SearchFilters())
    assert fake_model["documents"] == 0


# ---------- find_target() ----------

ACTIVE = [RecordStatus.ACTIVE]


def ids(records):
    return [r.id for r in records]


def test_target_single_exact(db, user):
    target = add(db, user, "Встреча с Иваном", at(5), type=RecordType.MEETING)
    add(db, user, "Встреча с Ольгой", at(5), type=RecordType.MEETING)

    match = find_target(db, user, "встречу с Иваном", None, None, ACTIVE)

    assert ids(match.exact) == [target.id]
    assert match.similar == []


def test_target_several_exact_earliest_first(db, user):
    late = add(db, user, "Позвонить Марией", at(20))
    early = add(db, user, "Позвонить Марией", at(3))
    match = find_target(db, user, "позвонить Марии", None, None, ACTIVE)
    assert ids(match.exact) == [early.id, late.id]


def test_target_when_same_day_and_time_first(db, user):
    exact_slot = add(db, user, "Созвон с Севером", at(6, 15), type=RecordType.MEETING)
    add(db, user, "Созвон с Севером", at(6, 11), type=RecordType.MEETING)  # тот же день
    add(db, user, "Созвон с Севером", at(9, 15), type=RecordType.MEETING)  # то же время

    match = find_target(db, user, "созвон с Севером", at(6, 15), None, ACTIVE)

    assert ids(match.exact) == [exact_slot.id]


def test_target_when_then_same_day(db, user):
    morning = add(db, user, "Созвон с Севером", at(6, 9), type=RecordType.MEETING)
    evening = add(db, user, "Созвон с Севером", at(6, 18), type=RecordType.MEETING)
    add(db, user, "Созвон с Севером", at(7, 15), type=RecordType.MEETING)

    match = find_target(db, user, "созвон с Севером", at(6, 15), None, ACTIVE)

    assert ids(match.exact) == [morning.id, evening.id]


def test_target_when_then_same_time_other_day(db, user):
    same_time = add(db, user, "Созвон с Севером", at(9, 15), type=RecordType.MEETING)
    add(db, user, "Созвон с Севером", at(10, 11), type=RecordType.MEETING)

    match = find_target(db, user, "созвон с Севером", at(6, 15), None, ACTIVE)

    assert ids(match.exact) == [same_time.id]


def test_target_when_compared_in_users_timezone(db, user):
    # 02:00 6-го по Москве — 23:00 5-го по UTC: день сравнивается в поясе `when`, а не в UTC.
    early = add(db, user, "Созвон с Севером", at(6, 2), type=RecordType.MEETING)
    add(db, user, "Созвон с Севером", at(5, 12), type=RecordType.MEETING)
    match = find_target(db, user, "созвон с Севером", at(6, 0), None, ACTIVE)
    assert ids(match.exact) == [early.id]


def test_target_day_only_when_matches_day_not_midnight_elsewhere(db, user):
    # «Отмени созвон в пятницу»: день без времени приходит как 00:00 — сравнивается только день.
    friday = add(db, user, "Созвон с Севером", at(6, 15), type=RecordType.MEETING)
    add(db, user, "Созвон с Севером", at(9, 0), type=RecordType.MEETING)  # 00:00 другого дня
    match = find_target(db, user, "созвон с Севером", at(6, 0), None, ACTIVE)
    assert ids(match.exact) == [friday.id]


def test_target_all_day_record_has_no_time(db, user):
    # «Весь день» хранится как 00:00 — по времени «в 00:00 другого дня» он не совпадает.
    add(db, user, "Сдать смету", at(9, 0), all_day=True)
    match = find_target(db, user, "смету", at(6, 0), None, ACTIVE)
    assert match.exact == []


def test_target_words_match_but_when_does_not_goes_to_similar(db, user):
    rows = [add(db, user, "Созвон с Севером", at(d, 11), type=RecordType.MEETING)
            for d in (2, 12, 14, 28)]

    match = find_target(db, user, "созвон с Севером", at(13, 15), None, ACTIVE)

    assert match.exact == []
    # Три ближайшие ко времени, по порядку дат: 12, 14 и 2 (28 — дальше всех).
    assert ids(match.similar) == [rows[0].id, rows[1].id, rows[2].id]


def test_target_similar_by_meaning_never_exact(db, user):
    # «Созвон с Севером по CRM» нет — есть «по новому продукту». Менять её нельзя, только спросить.
    neighbour = add(db, user, "Созвон с Севером по новому продукту", at(5),
                    type=RecordType.MEETING)

    match = find_target(db, user, "созвон с Севером по CRM", None, None, ACTIVE)

    assert match.exact == []
    assert ids(match.similar) == [neighbour.id]


def test_target_similar_at_most_three(db, user):
    for d in range(1, 6):
        add(db, user, f"Позвонить Дмитрием {d}", at(d))
    match = find_target(db, user, "звонок Дмитрию", None, None, ACTIVE)
    assert match.exact == []
    assert len(match.similar) == core.TARGET_SIMILAR_LIMIT


def test_target_nothing(db, user):
    add(db, user, "Купить молоко", at(5))
    match = find_target(db, user, "встречу с дизайнером", None, None, ACTIVE)
    assert match.exact == [] and match.similar == []


def test_target_without_text_takes_all_by_filters(db, user):
    first = add(db, user, "Созвон с Севером", at(6, 9), type=RecordType.MEETING)
    second = add(db, user, "Подписать договор", at(6, 18))
    add(db, user, "Созвон с Севером", at(7, 9), type=RecordType.MEETING)  # другой день

    tomorrow = SearchFilters(date_from=at(6, 0), date_to=at(7, 0))
    match = find_target(db, user, None, None, tomorrow, ACTIVE)

    assert ids(match.exact) == [first.id, second.id]


def test_target_statuses(db, user):
    done = add(db, user, "Подписать договор", at(5), status=RecordStatus.DONE)
    add(db, user, "Подписать договор", at(6))

    match = find_target(db, user, "договор", None, None,
                        [RecordStatus.DONE, RecordStatus.CANCELLED])

    assert ids(match.exact) == [done.id]


def test_target_limit(db, user):
    for i in range(25):
        add(db, user, "Подписать договор", at(1) + timedelta(hours=i))
    match = find_target(db, user, "договор", None, None, ACTIVE)
    assert len(match.exact) == 21
