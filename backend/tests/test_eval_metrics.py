"""Метрики бенчмарка агента (`eval.metrics`) на заданных строках прогона."""

import pytest

from eval.metrics import Share, agent_metrics


def row(case_id, passed, turns, *, run=1, category="создание", skipped=None):
    return {"label": "t", "model": "m", "commit": "abc", "dataset": "d", "case_id": case_id,
            "category": category, "run": run, "skipped": skipped, "passed": passed,
            "turns": turns}


def turn(expected, observed, fields=None, latency=1000.0):
    return {"expected": {"action": expected}, "observed_action": observed,
            "fields": {"action": expected.split("|")[0] == observed or observed in
                       expected.split("|"), **(fields or {})},
            "latency_ms": latency, "latency_clean": True}


def test_wilson_interval_is_inside_zero_one_and_contains_rate():
    for hits, total in [(0, 10), (10, 10), (9, 10), (167, 176)]:
        lo, hi = Share(hits, total).interval
        assert 0.0 <= lo <= hits / total <= hi <= 1.0
    # Известное значение: 9 из 10 → [0,596; 0,982]
    lo, hi = Share(9, 10).interval
    assert lo == pytest.approx(0.596, abs=0.001) and hi == pytest.approx(0.982, abs=0.001)


def test_case_share_pass_k_and_categories():
    rows = [
        row("1", True, [turn("create_record", "create_record")], run=1),
        row("1", False, [turn("create_record", "ask_user")], run=2),
        row("2", True, [turn("list_records", "list_records")], run=1, category="список"),
        row("2", True, [turn("list_records", "list_records")], run=2, category="список"),
        row("3", None, [], skipped="нужна база"),
    ]
    m = agent_metrics(rows)
    assert (m.cases.hits, m.cases.total) == (3, 4)
    assert (m.pass_k.hits, m.pass_k.total) == (1, 2)  # кейс 1 упал во втором повторе
    assert m.by_category["список"].rate == 1.0
    assert m.skipped == 1


def test_tool_confusion_and_f1():
    rows = [row(str(i), ok, [turn(e, o)]) for i, (e, o, ok) in enumerate([
        ("create_record", "create_record", True),
        ("create_record", "ask_user", False),
        ("search_records", "list_records", False),
        ("list_records", "list_records", True),
        ("list_records|ask_user", "ask_user", True),  # допустимы оба — засчитан вызванный
    ])]
    m = agent_metrics(rows)
    scores = {t.tool: t for t in m.tools}
    assert m.confusion["create_record"]["ask_user"] == 1
    assert scores["create_record"].recall == 0.5 and scores["create_record"].precision == 1.0
    assert scores["list_records"].precision == 0.5 and scores["list_records"].recall == 1.0
    assert scores["search_records"].f1 == 0.0
    assert scores["ask_user"].support == 1


def test_field_shares_and_latency_percentiles():
    rows = [row(str(i), True, [turn("create_record", "create_record",
                                    {"start": i % 2 == 0}, latency=float(i * 100))])
            for i in range(1, 11)]
    m = agent_metrics(rows)
    assert (m.fields["start"].hits, m.fields["start"].total) == (5, 10)
    assert m.latency_p50_ms == pytest.approx(550.0)
    assert m.latency_p95_ms == pytest.approx(955.0)
