"""Загрузка наборов `eval/datasets/agent/*.json`: все наборы проходят проверку, ошибки ловятся."""

import json

import pytest

from eval.cases import CASES, DatasetError, agent_datasets, load_dataset

GOOD_CASE = {
    "id": "x.1", "category": "создание",
    "turns": [{"text": "Напомни завтра в 10 позвонить Ивану",
               "expect": {"action": "create_record", "type": "reminder",
                          "title": ["позвон", "Иван"], "start": "2026-10-22 10:00"}}],
}


def dataset(*cases) -> dict:
    return {"dataset": "t", "source": "тест", "author": "тест", "now": "2026-10-21 10:00",
            "timezone": "Europe/Moscow", "cases": list(cases)}


def write(tmp_path, data) -> object:
    path = tmp_path / "t.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_all_repository_datasets_load():
    paths = agent_datasets()
    assert paths, "нет ни одного набора агента"
    for path in paths:
        load_dataset(path)  # падает с номером кейса, если набор неверный


def test_reference_cases_are_loaded_with_categories():
    assert len(CASES) == 181
    assert all(c.category for c in CASES)


def test_good_case_loads(tmp_path):
    loaded = load_dataset(write(tmp_path, dataset(GOOD_CASE)))
    expect = loaded.cases[0].turns[0].expect
    assert expect.title == ("позвон", "Иван") and expect.start == "2026-10-22 10:00"


@pytest.mark.parametrize("change, message", [
    ({"action": "create_reminder"}, "неизвестный инструмент"),
    ({"start": "22.10.2026 10:00"}, "не в формате"),
    ({"target_index": 2}, "target_index"),
    ({"priority": "high"}, "priority"),
    ({"awaiting": "maybe"}, "awaiting"),
])
def test_wrong_expectation_is_rejected(tmp_path, change, message):
    case = json.loads(json.dumps(GOOD_CASE))
    case["turns"][0]["expect"].update(change)
    with pytest.raises(DatasetError, match=message):
        load_dataset(write(tmp_path, dataset(case)))


def test_duplicate_id_is_rejected(tmp_path):
    with pytest.raises(DatasetError, match="повторяется"):
        load_dataset(write(tmp_path, dataset(GOOD_CASE, GOOD_CASE)))
