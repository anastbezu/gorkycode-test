"""Отчёт по прогону агента: md с таблицами и графики PNG.

    cd backend
    uv run --group eval python -m eval.report develop-1        # eval/results/agent/develop-1.jsonl

Пишет `eval/reports/agent-<label>/report.md` и рядом графики: доля пройденных по категориям
с 95 % интервалом, матрица ошибок выбора инструмента, доля верных по полям.
Цифры — только из файла прогона (`eval.metrics`); отчёт своих не добавляет.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from eval.metrics import AgentMetrics, Share, agent_metrics, load_rows

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results" / "agent"
REPORTS_DIR = EVAL_DIR / "reports"

# Подписи полей ожидания для людей.
FIELD_NAMES = {
    "type": "тип записи", "title": "название", "start": "начало (и «время названо»)",
    "end": "конец", "deadline": "срок", "date_from": "период: с", "date_to": "период: по",
    "types": "типы списка", "query": "запрос поиска", "query_from": "фильтр поиска: с",
    "query_to": "фильтр поиска: по", "kind": "справка / посторонняя тема",
    "status": "новый статус", "replaces_last": "«не этот, а тот»",
    "target_index": "цель: номер", "target_focus": "цель: «её»", "target_all": "цель: «все»",
    "target_text": "цель: описание", "ok": "исполнено", "awaiting": "ждёт ответа",
}


def _bars_with_interval(ax, labels: list[str], shares: list[Share], title: str) -> None:
    rates = [s.rate * 100 for s in shares]
    lows = [(s.rate - s.interval[0]) * 100 for s in shares]
    highs = [(s.interval[1] - s.rate) * 100 for s in shares]
    y = range(len(labels))
    ax.barh(list(y), rates, xerr=[lows, highs], color="#4C72B0", ecolor="#333333", capsize=3)
    ax.set_yticks(list(y), [f"{label} (n={s.total})" for label, s in zip(labels, shares,
                                                                        strict=True)])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("%, с 95 % интервалом Уилсона")
    ax.set_title(title)


def draw(metrics: AgentMetrics, out_dir: Path) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    files = {}

    fig, ax = plt.subplots(figsize=(8, 0.45 * len(metrics.by_category) + 1.5))
    _bars_with_interval(ax, list(metrics.by_category), list(metrics.by_category.values()),
                        "Пройдено кейсов по категориям")
    fig.tight_layout()
    fig.savefig(out_dir / "categories.png", dpi=150)
    plt.close(fig)
    files["categories"] = "categories.png"

    expected = list(metrics.confusion)
    observed = sorted({g for row in metrics.confusion.values() for g in row} | set(expected))
    matrix = [[metrics.confusion[e][o] for o in observed] for e in expected]
    fig, ax = plt.subplots(figsize=(max(7.0, 1.1 * len(observed) + 2), 0.6 * len(expected) + 1.8))
    sns.heatmap(matrix, annot=True, fmt="d", cmap="Blues", cbar=False, ax=ax,
                xticklabels=observed, yticklabels=expected)
    ax.set_xlabel("что вызвала модель")
    ax.set_ylabel("что ожидали")
    ax.set_title("Выбор инструмента: матрица ошибок (реплики)")
    plt.setp(ax.get_xticklabels(), rotation=35, ha="right")
    fig.tight_layout()
    fig.savefig(out_dir / "tools.png", dpi=150)
    plt.close(fig)
    files["tools"] = "tools.png"

    names = list(metrics.fields)
    fig, ax = plt.subplots(figsize=(8, 0.4 * len(names) + 1.5))
    _bars_with_interval(ax, [FIELD_NAMES.get(n, n) for n in names],
                        [metrics.fields[n] for n in names], "Верные поля вызова")
    fig.tight_layout()
    fig.savefig(out_dir / "fields.png", dpi=150)
    plt.close(fig)
    files["fields"] = "fields.png"
    return files


def render(metrics: AgentMetrics, files: dict[str, str], source: Path) -> str:
    m = metrics
    lines = [
        f"# Агент: прогон «{m.label}»",
        "",
        f"Модель `{m.model}`, коммит {', '.join(f'`{c}`' for c in m.commits)}, "
        f"повторов {m.runs}. Файл прогона — `{source.name}`. "
        f"Отчёт собран {datetime.now(UTC):%Y-%m-%d %H:%M} UTC.",
        "",
        "## Итог",
        "",
        "| Метрика | Значение |",
        "|---|---|",
        f"| Пройдено кейсов (кейс × повтор) | {m.cases.text()} |",
        f"| pass^{m.runs}: кейс прошёл во всех повторах | {m.pass_k.text()} |",
        f"| Выбор инструмента, macro-F1 | {m.macro_f1:.3f} |",
        f"| Время реплики, медиана / 95-й процентиль | {m.latency_p50_ms / 1000:.2f} с / "
        f"{m.latency_p95_ms / 1000:.2f} с |",
        f"| Пропущено кейсов (нет базы или своя причина) | {m.skipped} |",
        "",
        "В скобках — 95 % интервал Уилсона: где правда с такой выборкой.",
        "",
        "## По категориям",
        "",
        f"![категории]({files['categories']})",
        "",
        "| Категория | Пройдено |",
        "|---|---|",
        *(f"| {c} | {s.text()} |" for c, s in m.by_category.items()),
        "",
        "## Выбор инструмента",
        "",
        f"![инструменты]({files['tools']})",
        "",
        "| Инструмент | Precision | Recall | F1 | Реплик |",
        "|---|---|---|---|---|",
        *(f"| `{t.tool}` | {t.precision:.3f} | {t.recall:.3f} | {t.f1:.3f} | {t.support} |"
          for t in m.tools),
        "",
        "`none` — модель ничего не вызвала или код ответил без модели (отказ «не надо»).",
        "",
        "## Поля вызова",
        "",
        f"![поля]({files['fields']})",
        "",
        "| Поле | Верно |",
        "|---|---|",
        *(f"| {FIELD_NAMES.get(n, n)} | {s.text()} |" for n, s in m.fields.items()),
        "",
        "Неверный инструмент — поля засчитаны неверными.",
        "",
        f"## Провалы ({len(m.failed)})",
        "",
    ]
    for row in m.failed:
        turn = row["turns"][-1]
        lines += [
            f"- **{row['case_id']}** ({row['category']}, повтор {row['run']}) — "
            f"«{turn['text']}»",
            f"  - ожидалось: `{turn['expected']}`",
            f"  - вызвано: `{turn['observed_text']}`; ok={turn['ok']}, "
            f"awaiting={turn['awaiting']}",
            *(f"  - {p}" for p in turn["problems"]),
        ]
    lines += [
        "",
        "## Не измерено",
        "",
        "- Токены на реплику: прогон видит только действие модели, не `usage` ответа "
        "(закроется логами бэкенда).",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("label", help="метка прогона: eval/results/agent/<label>.jsonl")
    args = parser.parse_args()
    source = RESULTS_DIR / f"{args.label}.jsonl"
    if not source.exists():
        print(f"нет файла прогона {source}", file=sys.stderr)
        return 2
    metrics = agent_metrics(load_rows(source))
    out_dir = REPORTS_DIR / f"agent-{args.label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = draw(metrics, out_dir)
    (out_dir / "report.md").write_text(render(metrics, files, source), encoding="utf-8")
    print(f"готово: {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
