"""Файл кейсов `tests/agent_cases.py` и таблицы `docs/test-cases.md` не расходятся.

Маша поменяла таблицу — этот тест подскажет, что файл кейсов отстал (и наоборот).
Разделы 10 и 11 — справка и демо руками, в файл не входят.
"""

import re
from pathlib import Path

from tests.agent_cases import CASES

TEST_CASES_MD = Path(__file__).resolve().parents[2] / "docs" / "test-cases.md"


def _sections(text: str, first: int, last: int) -> str:
    start = text.index(f"\n## {first}.")
    end = text.index(f"\n## {last + 1}.")
    return text[start:end]


def _table_ids() -> set[str]:
    text = TEST_CASES_MD.read_text(encoding="utf-8")
    body = _sections(text, 1, 8)
    return set(re.findall(r"^\|\s*(\d+\.\d+[а-я]?)\s*\|", body, re.M))


def _table_expressions() -> set[str]:
    text = TEST_CASES_MD.read_text(encoding="utf-8")
    body = _sections(text, 9, 9)
    rows = re.findall(r"^\|\s*([^|]+?)\s*\|\s*[^|]+?\s*\|\s*$", body, re.M)
    return {r for r in rows if r != "Выражение" and not set(r) <= {"-"}}


def test_case_ids_match_table():
    in_file = {c.id for c in CASES if c.ref is None}
    in_table = _table_ids()
    assert sorted(in_table - in_file) == [], "кейсы есть в таблице, но не в файле"
    assert sorted(in_file - in_table) == [], "кейсы есть в файле, но не в таблице"


def test_date_expressions_match_table():
    in_file = {c.ref for c in CASES if c.ref is not None}
    in_table = _table_expressions()
    assert sorted(in_table - in_file) == [], "выражения раздела 9 не покрыты кейсами"
    assert sorted(in_file - in_table) == [], "кейсы ссылаются на выражения, которых нет"


def test_case_ids_are_unique():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))
