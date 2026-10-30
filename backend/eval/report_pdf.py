"""PDF общего отчёта по прогону агента (`eval.report`): текст, таблицы и графики в одном файле.

Шрифт — DejaVu Sans из поставки matplotlib (кириллица, без системных шрифтов).
"""

import os
from datetime import UTC, datetime
from pathlib import Path

from eval.metrics import AgentMetrics


def _font_dir() -> Path:
    import matplotlib

    return Path(matplotlib.get_data_path()) / "fonts" / "ttf"


def _plain(text: str) -> str:
    return text.replace("`", "")


def build_pdf(m: AgentMetrics, per_dataset: dict[str, AgentMetrics], files: dict[str, str],
              out_dir: Path) -> Path:
    from fpdf import FPDF
    from fpdf.fonts import FontFace

    from eval.report import DATASETS, FIELD_NAMES, LIMITS, summary_rows

    pdf = FPDF(format="A4")
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(True, margin=16)
    fonts = _font_dir()
    pdf.add_font("DejaVu", "", os.fspath(fonts / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", os.fspath(fonts / "DejaVuSans-Bold.ttf"))
    pdf.add_page()
    width = pdf.epw

    def heading(text: str, size: int = 13) -> None:
        pdf.ln(3)
        pdf.set_font("DejaVu", "B", size)
        pdf.multi_cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        pdf.set_font("DejaVu", "", 10)

    def para(text: str) -> None:
        pdf.set_font("DejaVu", "", 10)
        pdf.multi_cell(0, 5.2, _plain(text), markdown=True, new_x="LMARGIN",
                       new_y="NEXT")
        pdf.ln(1.5)

    def table(header: list[str], rows: list[list[str]], widths: list[float],
              size: float = 9) -> None:
        pdf.set_font("DejaVu", "", size)
        with pdf.table(col_widths=widths, line_height=size * 0.55, text_align="LEFT",
                       headings_style=FontFace(emphasis="BOLD", fill_color=(232, 236, 244))) as t:
            head = t.row()
            for cell in header:
                head.cell(cell)
            for row in rows:
                r = t.row()
                for cell in row:
                    r.cell(_plain(cell))
        pdf.ln(2)

    def image(name: str, w_share: float = 1.0) -> None:
        pdf.image(os.fspath(out_dir / files[name]), w=width * w_share,
                  x=pdf.l_margin + width * (1 - w_share) / 2)
        pdf.ln(2)

    turns = sum(t.support for t in m.tools)
    pdf.set_font("DejaVu", "B", 16)
    pdf.multi_cell(0, 8, "GORKY: замер качества агента голосового ассистента", align="C",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    pdf.multi_cell(0, 5.5, f"Модель агента {m.model} · коммит {', '.join(m.commits)} · "
                   f"{datetime.now(UTC):%d.%m.%Y}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    heading("Аннотация")
    para(f"Агент GORKY превращает фразу пользователя в вызов одного из восьми инструментов "
         f"(создать, показать за период, найти, изменить, сменить статус, откатить, "
         f"переспросить, справка), код исполняет вызов на базе. Замер — {m.cases.total} "
         f"кейсов в {len(m.by_dataset)} наборах, {turns} реплик, на настоящей модели и "
         f"настоящей базе. Пройдено **{m.cases.text()}** кейсов; выбор инструмента — "
         f"macro-F1 **{m.macro_f1:.3f}**; медиана времени реплики — "
         f"**{m.latency_p50_ms / 1000:.2f} с**.")

    heading("1. Как измеряли")
    para("Кейс — фраза пользователя или диалог из нескольких реплик и ожидание на каждой "
         "реплике: какой инструмент вызван, значения его полей (тип, название, даты, период, "
         "запрос, цель изменения) и исход действия (исполнено, ждёт ответа, ждёт выбора). "
         "Проверяются только заданные в ожидании поля; названия и запросы — по основам слов, "
         "даты — с точностью до минуты в поясе пользователя. «Сейчас» во всех кейсах — "
         "среда 21.10.2026, 10:00, Europe/Moscow. Кейсы с записями пользователя исполняются "
         "на PostgreSQL с настоящим поиском; каждый кейс — в своей транзакции с откатом.")
    table(["Набор", "Что проверяет", "Кейсов", "Реплик"],
          [[d, DATASETS.get(d, ""), str(p.cases.total), str(sum(t.support for t in p.tools))]
           for d, p in per_dataset.items()], [16, 60, 12, 12])
    para("Метрики: доля пройденных кейсов (кейс пройден, если верны все реплики); по "
         "инструменту — precision, recall и F1 по матрице ошибок, macro-F1 — среднее F1 по "
         "инструментам; по полю — доля верных значений (если инструмент выбран неверно, все "
         "поля реплики считаются неверными); время реплики — медиана и 95-й процентиль.")

    heading("2. Результаты")
    table(["Метрика", "Значение"], [list(r) for r in summary_rows(m)], [70, 30], size=9.5)
    image("datasets", 0.85)
    table(["Набор", "Пройдено"], [[d, s.text()] for d, s in m.by_dataset.items()], [50, 50])

    heading("Выбор инструмента", 11)
    image("tools", 0.8)
    table(["Инструмент", "Precision", "Recall", "F1", "Реплик"],
          [[t.tool, f"{t.precision:.3f}", f"{t.recall:.3f}", f"{t.f1:.3f}", str(t.support)]
           for t in m.tools], [32, 17, 17, 17, 17])
    para("none — модель ничего не вызвала или код ответил без модели (отказ «не надо»).")

    heading("Поля вызова", 11)
    image("fields", 0.85)
    table(["Поле", "Верно"], [[FIELD_NAMES.get(n, n), s.text()] for n, s in m.fields.items()],
          [60, 40])

    heading("По категориям", 11)
    image("categories", 0.9)

    heading(f"3. Ошибки ({len(m.failed)})")
    rows = []
    for row in m.failed:
        turn = next(t for t in reversed(row["turns"]) if t["problems"])
        rows.append([row["dataset"], row["case_id"], f"«{turn['text']}»",
                     "; ".join(turn["problems"])])
    table(["Набор", "Кейс", "Фраза", "Что не так"], rows, [14, 10, 34, 42], size=8)

    heading("4. Ограничения")
    for limit in LIMITS:
        para(f"— {limit}")
    para("Данные: наборы — backend/eval/datasets/agent/, ответы агента на каждый кейс — "
         f"backend/eval/results/agent/{m.label}.jsonl, отчёты по наборам — "
         f"backend/eval/reports/agent-{m.label}/.")

    path = out_dir / "report.pdf"
    pdf.output(os.fspath(path))
    return path
