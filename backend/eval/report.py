"""Отчёт по прогону агента: md — общий и по каждому набору, графики PNG и PDF.

    cd backend
    uv run --group eval python -m eval.report final        # eval/results/agent/final.jsonl

Пишет в `eval/reports/agent-<label>/`: `report.md` (общий), `<набор>.md` (по набору),
`report.pdf` (общий отчёт целиком, с графиками) и графики: доля пройденных по наборам и
категориям, матрица ошибок выбора инструмента, доля верных по полям.
Цифры — только из файла прогона (`eval.metrics`); отчёт своих не добавляет.
"""

import argparse
import json
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

# Что проверяет каждый набор — для таблицы «Метод».
DATASETS = {
    "test-cases": "кейсы команды (`docs/test-cases.md`): примеры из задания и сценарии продукта",
    "create": "создание: тип, название, начало, срок, конец, «время названо»",
    "list": "список за период: границы периода, типы записей",
    "search": "поиск: запрос, фильтры, отличие от списка",
    "update": "изменение: цель (номер, «её», описание), новые значения, исходы",
    "status": "выполнено / отменено / вернуть, массовые, «не эту, а ту»",
    "dialog": "диалог: уточнение, выбор, подтверждение, отказ, смена темы",
    "traps": "подвохи выбора инструмента: справка, посторонняя тема, две команды, отрицание",
    "undo": "«верни как было» после создания, переноса, смены статуса",
}

LIMITS = [
    "Кейсы наборов, кроме `test-cases`, сгенерированы моделью Gemini 3.8 Flash (high "
    "reasoning) по контрактам репозитория (`docs/contracts/`); ожидание — то, что однозначно "
    "следует из контракта. Набор `test-cases` составлен командой.",
    "Один прогон, повторов 1: разброс ответов модели между прогонами не измерен.",
    "Измерена одна модель агента; другие модели не сравнивались.",
    "Проверяются вызов инструмента, его поля и исход действия на настоящей базе, а не "
    "формулировка ответа пользователю.",
    "Голос (распознавание и синтез речи) не измерялся: на вход агенту подаётся текст.",
    "Время реплики — от текста пользователя до готового ответа, с исполнением на локальной "
    "базе; без пауз, которые прогон делает между вызовами модели.",
]


def _bars(ax, labels: list[str], shares: list[Share], title: str) -> None:
    rates = [s.rate * 100 for s in shares]
    y = range(len(labels))
    ax.barh(list(y), rates, color="#4C72B0")
    ax.set_yticks(list(y), [f"{label} (n={s.total})" for label, s in zip(labels, shares,
                                                                        strict=True)])
    for i, rate in enumerate(rates):
        ax.text(min(rate + 1, 92), i, f"{rate:.0f}%", va="center", fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("%")
    ax.set_title(title)


def draw(metrics: AgentMetrics, out_dir: Path) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    files = {}

    def save(fig, name: str) -> None:
        fig.tight_layout()
        fig.savefig(out_dir / f"{name}.png", dpi=150)
        plt.close(fig)
        files[name] = f"{name}.png"

    fig, ax = plt.subplots(figsize=(8, 0.45 * len(metrics.by_dataset) + 1.5))
    _bars(ax, list(metrics.by_dataset), list(metrics.by_dataset.values()),
          "Пройдено кейсов по наборам")
    save(fig, "datasets")

    fig, ax = plt.subplots(figsize=(8, 0.3 * len(metrics.by_category) + 1.5))
    _bars(ax, list(metrics.by_category), list(metrics.by_category.values()),
          "Пройдено кейсов по категориям")
    save(fig, "categories")

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
    save(fig, "tools")

    names = list(metrics.fields)
    fig, ax = plt.subplots(figsize=(8, 0.4 * len(names) + 1.5))
    _bars(ax, [FIELD_NAMES.get(n, n) for n in names], [metrics.fields[n] for n in names],
          "Верные поля вызова")
    save(fig, "fields")
    return files


def _expected_text(expected: dict) -> str:
    return json.dumps(expected, ensure_ascii=False)


def summary_rows(m: AgentMetrics) -> list[tuple[str, str]]:
    return [
        ("Пройдено кейсов", m.cases.text()),
        ("Выбор инструмента, macro-F1", f"{m.macro_f1:.3f}"),
        ("Время реплики, медиана / 95-й процентиль",
         f"{m.latency_p50_ms / 1000:.2f} с / {m.latency_p95_ms / 1000:.2f} с"),
        ("Не прогонялись (проверка в интерфейсе или другим набором)", str(m.skipped)),
    ]


def _tables(m: AgentMetrics) -> list[str]:
    return [
        "## Выбор инструмента",
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
        "| Поле | Верно |",
        "|---|---|",
        *(f"| {FIELD_NAMES.get(n, n)} | {s.text()} |" for n, s in m.fields.items()),
        "",
        "Неверный инструмент — поля засчитаны неверными.",
        "",
    ]


def _failures(m: AgentMetrics) -> list[str]:
    lines = [f"## Ошибки ({len(m.failed)})", ""]
    for row in m.failed:
        turn = next(t for t in reversed(row["turns"]) if t["problems"])
        lines += [
            f"- **{row['case_id']}** ({row['category']}) — «{turn['text']}»",
            f"  - ожидалось: `{_expected_text(turn['expected'])}`",
            f"  - вызвано: `{turn['observed_text']}`",
            *(f"  - {p}" for p in turn["problems"]),
        ]
    return lines + [""]


def render(m: AgentMetrics, files: dict[str, str], source: Path) -> str:
    lines = [
        f"# Агент: прогон «{m.label}»",
        "",
        f"Модель агента `{m.model}`, коммит {', '.join(f'`{c}`' for c in m.commits)}. "
        f"Файл прогона — `{source.name}`. Отчёт собран {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. "
        "Тот же отчёт с графиками — `report.pdf`.",
        "",
        "## Итог",
        "",
        "| Метрика | Значение |",
        "|---|---|",
        *(f"| {k} | {v} |" for k, v in summary_rows(m)),
        "",
        "## По наборам",
        "",
        f"![наборы]({files['datasets']})",
        "",
        "| Набор | Что проверяет | Пройдено |",
        "|---|---|---|",
        *(f"| [{d}]({d}.md) | {DATASETS.get(d, '')} | {s.text()} |"
          for d, s in m.by_dataset.items()),
        "",
        "## По категориям",
        "",
        f"![категории]({files['categories']})",
        "",
        "| Категория | Пройдено |",
        "|---|---|",
        *(f"| {c} | {s.text()} |" for c, s in m.by_category.items()),
        "",
        f"![инструменты]({files['tools']})",
        "",
        *_tables(m),
        f"![поля]({files['fields']})",
        "",
        *_failures(m),
        "## Ограничения",
        "",
        *(f"- {limit}" for limit in LIMITS),
    ]
    return "\n".join(lines) + "\n"


def render_dataset(name: str, m: AgentMetrics) -> str:
    lines = [
        f"# Набор `{name}`",
        "",
        f"{DATASETS.get(name, '')}. Модель агента `{m.model}`. "
        "Общий отчёт — [report.md](report.md).",
        "",
        "| Метрика | Значение |",
        "|---|---|",
        *(f"| {k} | {v} |" for k, v in summary_rows(m)),
        "",
        "## По категориям",
        "",
        "| Категория | Пройдено |",
        "|---|---|",
        *(f"| {c} | {s.text()} |" for c, s in m.by_category.items()),
        "",
        *_tables(m),
        *_failures(m),
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
    rows = load_rows(source)
    metrics = agent_metrics(rows)
    metrics.label = args.label  # склеенный из частей прогон — метка файла, не первой строки
    out_dir = REPORTS_DIR / f"agent-{args.label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = draw(metrics, out_dir)
    (out_dir / "report.md").write_text(render(metrics, files, source), encoding="utf-8")
    per_dataset = {}
    for name in metrics.by_dataset:
        part = agent_metrics([r for r in rows if r["dataset"] == name])
        per_dataset[name] = part
        (out_dir / f"{name}.md").write_text(render_dataset(name, part), encoding="utf-8")

    from eval.report_pdf import build_pdf

    build_pdf(metrics, per_dataset, files, out_dir)
    print(f"готово: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
