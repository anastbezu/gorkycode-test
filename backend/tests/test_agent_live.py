"""Живой слой автотеста: эталонные фразы через настоящую модель (agent-08).

Запускается руками перед мержем PR, который трогает системный промпт, инструменты или
схемы действий. В CI пропускается: ключа LLM там нет, и прогон стоит 100–200 вызовов.

    $env:AGENT_LIVE="1"; uv run pytest -m live -s                    # весь набор
    $env:AGENT_LIVE="1"; $env:AGENT_SECTION="2"; uv run pytest -m live -s   # раздел 2

Переменные: AGENT_SECTION — разделы через запятую; AGENT_PAUSE — пауза перед вызовом
модели, с (по умолчанию 4); AGENT_MIN_RATE — минимальная доля прошедших, % (по умолчанию 0).
"""

import os

import pytest
from dotenv import load_dotenv

from tests.agent_live import Harness, render, select_cases

pytestmark = pytest.mark.live


def test_live_reference_cases(monkeypatch, capsys):
    if os.environ.get("AGENT_LIVE") != "1":
        pytest.skip("живой прогон выключен: запуск — AGENT_LIVE=1 и ключ LLM, "
                    "см. docs/modules/agent.md, «Автотест»")
    load_dotenv()
    if not os.environ.get("LLM_API_KEY") or not os.environ.get("LLM_MODEL"):
        pytest.skip("живой прогон: нет LLM_API_KEY или LLM_MODEL в окружении / .env")

    from agent import agent as agent_module
    from agent.agent import get_action  # настоящая модель, до подмены в Harness

    real_make_client = agent_module.make_client
    timeout = float(os.environ.get("AGENT_TIMEOUT", "60"))

    def make_client_with_timeout(llm_config):
        # Только для живого прогона: провайдер бывает медленнее таймаута продукта (15 с).
        client, model = real_make_client(llm_config)
        return client.with_options(timeout=timeout), model

    monkeypatch.setattr(agent_module, "make_client", make_client_with_timeout)

    harness = Harness(monkeypatch, get_action, pause=float(os.environ.get("AGENT_PAUSE", "4")))
    cases = select_cases(os.environ.get("AGENT_SECTION"))
    todo = [c for c in cases if c.skip is None]
    reports = []
    for number, case in enumerate(todo, 1):
        report = harness.run_case(case)
        reports.append(report)
        with capsys.disabled():
            mark = "ок" if report.passed else "УПАЛ"
            print(f"[{number}/{len(todo)}] {case.id}: {mark}", flush=True)
        if harness.provider_failures >= 3:
            pytest.skip("живой прогон прерван: модель не ответила три кейса подряд "
                        "(таймаут или ошибка провайдера) — повторите позже")
    text = render(reports, skipped=[c for c in cases if c.skip is not None])
    with capsys.disabled():
        print("\n" + text)

    passed = sum(r.passed for r in reports)
    rate = passed / len(reports) * 100 if reports else 100.0
    assert rate >= float(os.environ.get("AGENT_MIN_RATE", "0")), text
