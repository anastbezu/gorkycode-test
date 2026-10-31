"""Метрики агента из файла прогона `eval/results/agent/<label>.jsonl` (`eval.run_agent`).

- доля пройденных кейсов — всего, по наборам и по категориям;
- pass^k — кейс прошёл во всех k повторах (устойчивость: один и тот же ответ на ту же фразу);
- выбор инструмента — матрица ошибок, precision / recall / F1 по инструменту, macro-F1;
- поля — доля верных по каждому проверяемому полю; инструмент выбран неверно — поля неверны;
- время реплики — медиана и 95-й процентиль.

Единица для кейсов — кейс × повтор; для инструментов и полей — реплика.
Пропущенные кейсы (нет базы, своя причина) в доли не входят — их число в отчёте отдельно.
"""

import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

Z95 = 1.959964  # 95 % двусторонний квантиль нормального распределения
NOTHING = "none"  # модель ничего не вызвала (или код ответил без модели)


@dataclass(frozen=True)
class Share:
    hits: int
    total: int

    @property
    def rate(self) -> float:
        return self.hits / self.total if self.total else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        """95 % интервал Уилсона: честен и при долях около 0 и 1, в отличие от «±1,96·σ»."""
        n, p = self.total, self.rate
        if n == 0:
            return (0.0, 0.0)
        centre = (p + Z95**2 / (2 * n)) / (1 + Z95**2 / n)
        half = Z95 * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n * n)) / (1 + Z95**2 / n)
        # Границы при 0 и n ровно 0 и 1 (в арифметике с плавающей точкой выходит 0,999…).
        lo = 0.0 if self.hits == 0 else max(0.0, centre - half)
        hi = 1.0 if self.hits == n else min(1.0, centre + half)
        return (lo, hi)

    def text(self) -> str:
        return f"{self.hits}/{self.total} = {self.rate:.1%}"


@dataclass
class ToolScore:
    tool: str
    precision: float
    recall: float
    f1: float
    support: int  # сколько реплик ждали этот инструмент


@dataclass
class AgentMetrics:
    label: str
    model: str
    commits: list[str]
    runs: int
    skipped: int
    cases: Share
    by_category: dict[str, Share]
    by_dataset: dict[str, Share]
    pass_k: Share  # кейс прошёл во всех повторах
    tools: list[ToolScore]
    macro_f1: float
    confusion: dict[str, Counter] = field(default_factory=dict)  # ожидали → что вызвала
    fields: dict[str, Share] = field(default_factory=dict)
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_clean: bool = True  # False — старый прогон: в время входили паузы между вызовами
    failed: list[dict] = field(default_factory=list)  # для разбора провалов


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def expected_tool(expected: str, observed: str | None) -> str:
    """Метка «правильного» инструмента: из допустимых «a|b» — вызванный, если он среди них."""
    options = expected.split("|")
    observed = observed or NOTHING
    return observed if observed in options else options[0]


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def agent_metrics(rows: list[dict]) -> AgentMetrics:
    done = [r for r in rows if r["skipped"] is None]
    skipped = len({(r["dataset"], r["case_id"]) for r in rows if r["skipped"] is not None})

    cases = Share(sum(r["passed"] for r in done), len(done))
    per_category: dict[str, list[bool]] = defaultdict(list)
    per_case: dict[tuple, list[bool]] = defaultdict(list)
    per_dataset: dict[str, list[bool]] = defaultdict(list)
    for r in done:
        per_category[r["category"]].append(r["passed"])
        per_dataset[r["dataset"]].append(r["passed"])
        per_case[(r["dataset"], r["case_id"])].append(r["passed"])
    by_category = {c: Share(sum(v), len(v)) for c, v in per_category.items()}
    pass_k = Share(sum(all(v) for v in per_case.values()), len(per_case))

    confusion: dict[str, Counter] = defaultdict(Counter)
    field_hits: dict[str, list[bool]] = defaultdict(list)
    latencies = []
    clean = True
    for r in done:
        for t in r["turns"]:
            got = t["observed_action"] or NOTHING
            confusion[expected_tool(t["expected"]["action"], got)][got] += 1
            for name, ok in t["fields"].items():
                if name != "action":
                    field_hits[name].append(ok)
            latencies.append(t["latency_ms"])
            clean = clean and t.get("latency_clean", False)

    labels = sorted(set(confusion) | {g for row in confusion.values() for g in row})
    tools = []
    for tool in labels:
        tp = confusion.get(tool, Counter())[tool]
        predicted = sum(row[tool] for row in confusion.values())
        support = sum(confusion.get(tool, Counter()).values())
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if support:  # инструмент, которого ни разу не ждали, в macro-F1 не входит
            tools.append(ToolScore(tool, precision, recall, f1, support))
    macro_f1 = statistics.fmean(t.f1 for t in tools) if tools else 0.0

    failed = [r for r in done if not r["passed"]]
    return AgentMetrics(
        label=rows[0]["label"] if rows else "",
        model=rows[0]["model"] if rows else "",
        commits=sorted({r["commit"] for r in rows}),
        runs=max((r["run"] for r in rows), default=0),
        skipped=skipped,
        cases=cases,
        by_category=dict(sorted(by_category.items())),
        by_dataset={d: Share(sum(v), len(v)) for d, v in per_dataset.items()},
        pass_k=pass_k,
        tools=tools,
        macro_f1=macro_f1,
        confusion={k: confusion[k] for k in labels if k in confusion},
        fields={k: Share(sum(v), len(v)) for k, v in sorted(field_hits.items())},
        latency_p50_ms=percentile(latencies, 0.5),
        latency_p95_ms=percentile(latencies, 0.95),
        latency_clean=clean,
        failed=failed,
    )
