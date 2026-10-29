"""Прогон наборов агента через настоящую модель — ответ на каждый кейс в файл.

    cd backend
    uv run python -m eval.run_agent --label develop-1                       # все наборы
    uv run python -m eval.run_agent --label develop-1 --runs 3              # три повтора
    uv run python -m eval.run_agent --label t --section 2,3                 # разделы 2 и 3
    uv run python -m eval.run_agent --label t --dataset eval/datasets/agent/test-cases.json

Результат — `eval/results/agent/<label>.jsonl`, строка на кейс × повтор: метка, коммит,
модель, набор, кейс, категория, прошёл ли, и по каждой реплике — ожидание, что вызвала
модель, ответ, расхождения, верность каждого поля, время. Метрики и отчёт из файла —
`eval.metrics` и `eval.report`.

Продолжение: строка пишется сразу после кейса. Прервался (лимит ключа, сеть) — тот же запуск
с той же меткой пропускает готовые кейсы. Модель не ответила 3 кейса подряд — прогон
останавливается; поменяйте `LLM_API_KEY` в `.env` и запустите снова.

База: с `TEST_DATABASE_URL` (иначе `DATABASE_URL`) — настоящие сервисы, каждый кейс в своей
транзакции, которая откатывается; без базы (`--no-db`) кейсы изменений пропускаются.
Модель и ключ — `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` из окружения или `.env`.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from eval.cases import NOW, TIMEZONE, Case, agent_datasets, load_dataset
from eval.compare import describe, field_verdicts
from eval.harness import TZ, CaseReport, Harness, skip_reason

RESULTS_DIR = Path(__file__).resolve().parent / "results" / "agent"
PROVIDER_FAILURES_TO_STOP = 3


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def done_keys(path: Path) -> set[tuple[str, str, int]]:
    """(набор, кейс, повтор), уже записанные в файл результата."""
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            keys.add((row["dataset"], row["case_id"], row["run"]))
    return keys


def action_dump(action) -> dict | None:
    if action is None:
        return None
    return json.loads(action.model_dump_json(exclude_none=True))


def case_row(meta: dict, dataset: str, case: Case, run: int, report: CaseReport | None,
             skipped: str | None) -> dict:
    row = {**meta, "dataset": dataset, "case_id": case.id, "category": case.category,
           "run": run, "skipped": skipped}
    if report is None:
        return {**row, "passed": None, "turns": []}
    turns = []
    for turn in report.turns:
        observed = turn.observed
        turns.append({
            "number": turn.number,
            "text": turn.text,
            "expected": {k: v for k, v in vars(turn.expect).items() if v not in (None, ())},
            "observed_action": getattr(observed.action, "action", None),
            "observed": action_dump(observed.action),
            "observed_text": describe(observed.action, TZ),
            "ok": observed.ok,
            "awaiting": observed.awaiting,
            "reply": turn.reply,
            "problems": turn.problems,
            "fields": field_verdicts(turn.expect, observed, TZ),
            "latency_ms": round(turn.latency_ms, 1),
        })
    return {**row, "passed": report.passed, "turns": turns}


def real_model(timeout: float):
    """Настоящий `get_action` с таймаутом прогона: провайдер бывает медленнее продукта (15 с)."""
    from agent import agent as agent_module
    from agent.agent import get_action

    real_make_client = agent_module.make_client

    def make_client_with_timeout(llm_config):
        client, model = real_make_client(llm_config)
        return client.with_options(timeout=timeout), model

    return get_action, ("make_client", make_client_with_timeout)


def run_case_once(case: Case, model, patch, *, engine, pause: float) -> CaseReport:
    """Кейс в своей среде: подмены на время кейса, база — транзакция с откатом."""
    mp = pytest.MonkeyPatch()
    from agent import agent as agent_module

    mp.setattr(agent_module, *patch)
    conn = trans = session = None
    try:
        if engine is not None:
            conn = engine.connect()
            trans = conn.begin()
            session = Session(bind=conn, join_transaction_mode="create_savepoint")
        harness = Harness(mp, model, db=session, pause=pause)
        report = harness.run_case(case)
        report.provider_failures = harness.provider_failures
        return report
    finally:
        if session is not None:
            session.close()
            trans.rollback()
            conn.close()
        mp.undo()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True, help="имя прогона — имя файла результата")
    parser.add_argument("--dataset", action="append", type=Path,
                        help="файл набора; можно несколько; по умолчанию все наборы агента")
    parser.add_argument("--section", help="только категории/разделы через запятую: 2,3")
    parser.add_argument("--runs", type=int, default=1, help="повторов каждого кейса")
    parser.add_argument("--pause", type=float, default=4.0, help="пауза перед вызовом модели, с")
    parser.add_argument("--timeout", type=float, default=60.0, help="таймаут вызова модели, с")
    parser.add_argument("--no-db", action="store_true", help="без базы: изменения пропускаются")
    args = parser.parse_args()

    load_dotenv()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    if not os.environ.get("LLM_API_KEY") or not os.environ.get("LLM_MODEL"):
        print("нет LLM_API_KEY или LLM_MODEL в окружении / .env", file=sys.stderr)
        return 2

    engine = None
    if not args.no_db:
        if url := os.environ.get("TEST_DATABASE_URL"):
            os.environ["DATABASE_URL"] = url
        from db.session import get_engine

        engine = get_engine()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{args.label}.jsonl"
    done = done_keys(out)
    meta = {"label": args.label, "commit": git_commit(), "model": os.environ["LLM_MODEL"],
            "started_at": datetime.now(UTC).isoformat(timespec="seconds")}
    model, patch = real_model(args.timeout)
    sections = {s.strip() for s in args.section.split(",")} if args.section else None

    failures_in_row = 0
    with out.open("a", encoding="utf-8") as sink:
        for path in args.dataset or agent_datasets():
            dataset = load_dataset(path)
            if (dataset.now, dataset.timezone) != (NOW, TIMEZONE):
                print(f"{path}: «сейчас» и пояс набора должны быть {NOW}, {TIMEZONE}",
                      file=sys.stderr)
                return 2
            cases = [c for c in dataset.cases
                     if sections is None or c.section in sections or c.category in sections]
            for run in range(1, args.runs + 1):
                for number, case in enumerate(cases, 1):
                    if (dataset.name, case.id, run) in done:
                        continue
                    reason = skip_reason(case, engine is not None)
                    report = None
                    if reason is None:
                        report = run_case_once(case, model, patch, engine=engine,
                                               pause=args.pause)
                        if report.provider_failures:
                            # Модель не ответила — это не ответ агента: кейс не пишется
                            # и при следующем запуске прогоняется снова.
                            failures_in_row += 1
                            print(f"[{dataset.name}] {case.id}: модель не ответила", flush=True)
                            if failures_in_row >= PROVIDER_FAILURES_TO_STOP:
                                print("модель не ответила 3 кейса подряд — смените ключ и "
                                      "запустите снова с той же меткой: готовые кейсы "
                                      "пропустятся", file=sys.stderr)
                                return 1
                            continue
                        failures_in_row = 0
                    row = case_row(meta, dataset.name, case, run, report, reason)
                    sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                    sink.flush()
                    mark = "пропуск" if reason else ("ок" if report.passed else "УПАЛ")
                    print(f"[{dataset.name} {run}/{args.runs} {number}/{len(cases)}] "
                          f"{case.id}: {mark}", flush=True)
    print(f"готово: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
