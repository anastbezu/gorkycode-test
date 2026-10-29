"""Проверочный набор поиска на настоящей модели и стартовом датасете (search-01).

Критерии постановки: hit@5 не ниже 29 из 30; на 6 запросах без ответа ни одного `exact`;
на 24 целях ни одной чужой записи. Набор и метрики — scripts/search_eval.py (там же
подробный отчёт: `uv run python -m scripts.search_eval`).

Нужны PostgreSQL с pgvector и модель в кэше Hugging Face (сеть тест не использует).
Модели нет — тест пропускается с причиной.
"""

import re
from pathlib import Path

import pytest

from scripts.search_eval import WRONG_RECORD, report, report_extended, run_eval, run_extended
from search import embeddings

pytestmark = pytest.mark.search_model


@pytest.fixture(scope="module")
def model_available():
    try:
        embeddings.embed_queries(["проверка"])
    except embeddings.ModelUnavailableError as exc:
        pytest.skip(f"модели поиска нет локально — проверочный набор пропущен: {exc}")


def test_check_set(db, model_available):
    result = run_eval(db)
    details = report(result)

    assert result.hits >= 29, details
    assert result.exact_without_answer == 0, details
    assert result.wrong_exact == [], details
    assert result.target_outcomes()[WRONG_RECORD] == 0, details


def test_extended_set_safety(db, model_available):
    # Расширенный набор (scripts/search_cases.py): сотни запросов и целей. Здесь — только то,
    # что нельзя нарушать никогда: чужая запись при изменении и «точно» там, где ответа нет.
    # Остальные метрики — в отчёте `uv run python -m scripts.search_eval --extended`.
    result = run_extended(db)
    details = report_extended(result)

    assert result.wrong_records == [], details
    assert result.false_exact_without_answer == [], details


def test_start_dataset_vectors_are_not_recomputed(db, model_available):
    first = run_eval(db)
    second = run_eval(db)  # второй новый пользователь с тем же стартовым набором
    assert first.vectors_computed > 0
    assert second.vectors_computed == 0


def test_search_model_pinned_in_dockerfile():
    # В образ скачивается та же модель и ревизия, что использует код.
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text("utf-8")
    assert re.search(rf"SEARCH_MODEL={re.escape(embeddings.MODEL_ID)}\b", dockerfile)
    assert f"SEARCH_MODEL_REVISION={embeddings.MODEL_REVISION}" in dockerfile
