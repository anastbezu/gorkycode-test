"""Расширенный проверочный набор поиска: сотни запросов и целей по всем граничным случаям.

Стартовый датасет собран из шаблонов: «Встреча с {человек} по {тема}», «Созвон с {компания}
по {тема}», «Позвонить {человек}», «Отправить {документ} {человек}» … (10 людей, 8 компаний,
10 тем, ~14 документов). Поэтому правильный ответ на запрос считается не правилом самого
поиска (это была бы проверка поиска самим собой), а независимо:
1. каждое название разбирается по шаблонам датасета (`TEMPLATES`) на понятия: действие,
   человек, компания, тема или документ;
2. запрос — набор понятий + текст, как его скажет пользователь; формы слов (падежи имён,
   «по бюджету» / «про бюджет», опечатки) выписаны здесь вручную;
3. подходящие записи — те, у кого есть все понятия запроса и которые проходят фильтры.

Группы случаев — граничные случаи поиска (имя `group` в отчёте):
- поиск: формы имён и компаний, темы, документы, человек + тема (все 100 пар — есть и нет
  в данных), действие + человек, синонимы и сокращения, опечатки, речь с паразитами,
  несуществующее, фильтры типа и периода, пустые и странные запросы;
- цели изменения: одна запись, несколько, с датой и временем, с чужой датой, сочетания,
  которых нет, «встречу» там, где есть только задача, «верни» среди выполненных, без описания.
"""

import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from schemas import RecordStatus, RecordType, SearchFilters

# ---------- словари форм (вручную) ----------

# Человек: им., род., дат., вин., твор. В названиях датасета — всегда творительный («Иваном»).
PEOPLE = {
    "Мария": ("Мария", "Марии", "Марии", "Марию", "Марией"),
    "Алексей": ("Алексей", "Алексея", "Алексею", "Алексея", "Алексеем"),
    "Елена": ("Елена", "Елены", "Елене", "Елену", "Еленой"),
    "Максим": ("Максим", "Максима", "Максиму", "Максима", "Максимом"),
    "Анна": ("Анна", "Анны", "Анне", "Анну", "Анной"),
    "Дмитрий": ("Дмитрий", "Дмитрия", "Дмитрию", "Дмитрия", "Дмитрием"),
    "Наталья": ("Наталья", "Натальи", "Наталье", "Наталью", "Натальей"),
    "Иван": ("Иван", "Ивана", "Ивану", "Ивана", "Иваном"),
    "Ольга": ("Ольга", "Ольги", "Ольге", "Ольгу", "Ольгой"),
    "Сергей": ("Сергей", "Сергея", "Сергею", "Сергея", "Сергеем"),
}
NOM, GEN, DAT, ACC, INS = range(5)

# Компания: им., род., твор.
COMPANIES = {
    "Альфа": ("Альфа", "Альфы", "Альфой"),
    "Север": ("Север", "Севера", "Севером"),
    "Орбита": ("Орбита", "Орбиты", "Орбитой"),
    "Пульс": ("Пульс", "Пульса", "Пульсом"),
    "Маяк": ("Маяк", "Маяка", "Маяком"),
    "Старт": ("Старт", "Старта", "Стартом"),
    "Вектор": ("Вектор", "Вектора", "Вектором"),
    "Партнёр": ("Партнёр", "Партнёра", "Партнёром"),
}

# Тема: им. («бюджет»), дат. после «по» — как в датасете («по бюджету»), вин. после «про».
TOPICS = {
    "интеграция": ("интеграция", "интеграции", "интеграцию"),
    "презентация": ("презентация", "презентации", "презентацию"),
    "договор": ("договор", "договору", "договор"),
    "новый продукт": ("новый продукт", "новому продукту", "новый продукт"),
    "сайт": ("сайт", "сайту", "сайт"),
    "аналитика": ("аналитика", "аналитике", "аналитику"),
    "бюджет": ("бюджет", "бюджету", "бюджет"),
    "хакатон": ("хакатон", "хакатону", "хакатон"),
    "мобильное приложение": ("мобильное приложение", "мобильному приложению",
                             "мобильное приложение"),
    "CRM": ("CRM", "CRM", "CRM"),
}

# Документ: им., вин. Формы в названиях датасета → понятие.
DOCUMENTS = {
    "договор": ("договор", "договор"),
    "презентация": ("презентация", "презентацию"),
    "протокол": ("протокол", "протокол"),
    "акт": ("акт", "акт"),
    "смета": ("смета", "смету"),
    "отчёт": ("отчёт", "отчёт"),
    "техническое задание": ("техническое задание", "техническое задание"),
    "коммерческое предложение": ("коммерческое предложение", "коммерческое предложение"),
    "итоги встречи": ("итоги встречи", "итоги встречи"),
    "вопросы": ("вопросы", "вопросы"),
    "материалы": ("материалы", "материалы"),
    "обратная связь": ("обратная связь", "обратную связь"),
    "сроки": ("сроки", "сроки"),
    "статус задачи": ("статус задачи", "статус задачи"),
    "бюджет": ("бюджет", "бюджет"),
}

_PERSON_IN_TITLE = {forms[INS]: name for name, forms in PEOPLE.items()}
_COMPANY_IN_TITLE = {forms[2]: name for name, forms in COMPANIES.items()}
_TOPIC_IN_TITLE = {forms[1]: name for name, forms in TOPICS.items()}
_DOC_IN_TITLE = {forms[1]: name for name, forms in DOCUMENTS.items()}

# ---------- разбор названий датасета ----------

P, C, T, D = r"(?P<p>\w+)", r"(?P<c>\w+)", r"(?P<t>.+)", r"(?P<d>.+)"
# (шаблон названия, действие, документ по умолчанию). Порядок важен: частные — раньше общих.
TEMPLATES = [
    (rf"^Напомнить {P} про {T}$", "напомнить", None),
    (rf"^Встреча с {P} по {T}$", "встреча", None),
    (rf"^Созвон с {C} по {T}$", "созвон", None),
    (rf"^Подготовить вопросы для {P}$", "подготовить", "вопросы"),
    (rf"^Позвонить {P}$", "позвонить", None),
    (rf"^Отправить итоги встречи {P}$", "отправить", "итоги встречи"),
    (rf"^Демо проекта по {T}$", "демо", None),
    (rf"^Провести планёрку по {T}$", "планёрка", None),
    (rf"^Собрать обратную связь по {T}$", "собрать", "обратная связь"),
    (rf"^Проверить сроки по {T}$", "проверить", "сроки"),
    (rf"^Проверить статус задачи по {T}$", "проверить", "статус задачи"),
    (rf"^Обновить материалы по {T}$", "обновить", "материалы"),
    (rf"^Обсудить бюджет по {T}$", "обсудить", "бюджет"),
    (rf"^Подготовиться к встрече с {C}$", "подготовиться", None),
    (rf"^Отправить {D} {P}$", "отправить", None),
    (rf"^Обсудить {T} с {P}$", "обсудить", None),
    (rf"^Согласовать {D} с {P}$", "согласовать", None),
    (rf"^Проверить {D} по {T}$", "проверить", None),
    (rf"^Передать {D} на согласование$", "передать", None),
    (rf"^Подготовить {D}$", "подготовить", None),
]
_COMPILED = [(re.compile(p), a, d) for p, a, d in TEMPLATES]


@dataclass(frozen=True)
class Concepts:
    """Понятия названия: действие, человек, компания и предметы (темы и документы)."""

    action: str
    person: str | None = None
    company: str | None = None
    subjects: frozenset[str] = frozenset()


def parse_title(title: str) -> Concepts:
    for pattern, action, doc in _COMPILED:
        m = pattern.match(title)
        if not m:
            continue
        g = m.groupdict()
        subjects = set()
        if doc:
            subjects.add(doc)
        if g.get("t"):
            subjects.add(_TOPIC_IN_TITLE[g["t"]])
        if g.get("d"):
            subjects.add(_DOC_IN_TITLE[g["d"]])
        return Concepts(
            action=action,
            person=_PERSON_IN_TITLE[g["p"]] if g.get("p") else None,
            company=_COMPANY_IN_TITLE[g["c"]] if g.get("c") else None,
            subjects=frozenset(subjects),
        )
    raise ValueError(f"название не подходит ни под один шаблон датасета: {title!r}")


# ---------- запрос: понятия, которые должны быть у подходящей записи ----------

MEETING_ACTIONS = frozenset({"встреча", "созвон", "демо", "планёрка"})


@dataclass(frozen=True)
class Need:
    """Что должно быть у подходящей записи. Пустые поля — без ограничения."""

    actions: frozenset[str] = frozenset()  # одно из действий
    person: str | None = None
    company: str | None = None
    subjects: frozenset[str] = frozenset()  # все предметы
    types: frozenset[RecordType] = frozenset()  # тип записи (пользователь назвал «встречу»)
    nothing: bool = False  # ответа в данных быть не может (несуществующее)

    def matches(self, c: Concepts, record_type: RecordType) -> bool:
        if self.nothing:
            return False
        if self.actions and c.action not in self.actions:
            return False
        if self.person and c.person != self.person:
            return False
        if self.company and c.company != self.company:
            return False
        if not self.subjects <= c.subjects:
            return False
        return not (self.types and record_type not in self.types)


@dataclass
class SearchCase:
    group: str
    query: str
    need: Need
    filters: SearchFilters = field(default_factory=SearchFilters)
    note: str = ""


@dataclass
class TargetCase:
    group: str
    text: str | None
    need: Need
    when: datetime | None = None
    when_kind: str | None = None  # "date" — назван день, "datetime" — день и время
    statuses: list[RecordStatus] = field(default_factory=lambda: [RecordStatus.ACTIVE])
    filters: SearchFilters | None = None
    note: str = ""


# ---------- поиск ----------

def _typo(word: str, rng: random.Random) -> str:
    """Одна опечатка: пропуск, замена соседней буквой или перестановка двух букв."""
    if len(word) < 4:
        return word
    i = rng.randrange(1, len(word) - 1)
    kind = rng.choice(("drop", "swap", "replace"))
    if kind == "drop":
        return word[:i] + word[i + 1:]
    if kind == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    near = "аоеиуыэюяьй"
    return word[:i] + rng.choice([ch for ch in near if ch != word[i]]) + word[i + 1:]


def search_cases(now: datetime, seed: int = 20261029) -> list[SearchCase]:
    """`now` — «сейчас» прогона: от него считаются фильтры «прошлое» и «будущее»."""
    rng = random.Random(seed)
    out: list[SearchCase] = []
    add = out.append

    # Человек во всех падежах: «Сергей», «Сергея», «Сергею», «Сергеем».
    case_names = ("им.", "род.", "дат.", "вин.", "твор.")
    for name, forms in PEOPLE.items():
        for i, form in enumerate(forms):
            if i == ACC and forms[ACC] == forms[GEN]:
                continue
            add(SearchCase("человек: падежи", form, Need(person=name), note=case_names[i]))

    # Компания: им., род., твор.
    for name, forms in COMPANIES.items():
        for form in forms:
            add(SearchCase("компания: падежи", form, Need(company=name)))
        add(SearchCase("компания: «созвон с …»", f"созвон с {forms[2]}",
                       Need(actions=frozenset({"созвон"}), company=name)))

    # Тема: «бюджет», «по бюджету», «про бюджет».
    for name, (nom, dat, acc) in TOPICS.items():
        add(SearchCase("тема", nom, Need(subjects=frozenset({name}))))
        add(SearchCase("тема", f"по {dat}", Need(subjects=frozenset({name}))))
        if acc != nom:
            add(SearchCase("тема", f"про {acc}", Need(subjects=frozenset({name}))))

    # Документ: «смета», «смету».
    for name, (nom, acc) in DOCUMENTS.items():
        add(SearchCase("документ", nom, Need(subjects=frozenset({name}))))
        if acc != nom:
            add(SearchCase("документ", acc, Need(subjects=frozenset({name}))))

    # Человек + тема: все 100 пар; каких-то в данных нет — тогда ответа нет.
    for name, pf in PEOPLE.items():
        for topic, tf in TOPICS.items():
            need = Need(person=name, subjects=frozenset({topic}))
            add(SearchCase("человек + тема", f"{tf[NOM]} {pf[NOM]}", need, note="им. + им."))
            add(SearchCase("человек + тема", f"встреча с {pf[INS]} по {tf[1]}",
                           Need(actions=frozenset({"встреча"}), person=name,
                                subjects=frozenset({topic})), note="как в названии"))

    # Компания + тема: созвоны.
    for name, cf in COMPANIES.items():
        for topic, tf in TOPICS.items():
            add(SearchCase("компания + тема", f"созвон с {cf[2]} по {tf[1]}",
                           Need(actions=frozenset({"созвон"}), company=name,
                                subjects=frozenset({topic}))))

    # Действие + человек: «позвонить Сергею» (слова), «звонок Сергею», «звонил Сергею» (смысл).
    for name, pf in PEOPLE.items():
        need = Need(actions=frozenset({"позвонить"}), person=name)
        add(SearchCase("действие + человек", f"позвонить {pf[DAT]}", need, note="слова"))
        add(SearchCase("действие + человек: смысл", f"звонок {pf[DAT]}", need, note="синоним"))
        add(SearchCase("действие + человек: смысл", f"звонил {pf[DAT]}", need, note="синоним"))
        add(SearchCase("действие + человек", f"отправить {pf[DAT]}",
                       Need(actions=frozenset({"отправить"}), person=name)))
        add(SearchCase("действие + человек", f"напоминание {pf[DAT]}",
                       Need(actions=frozenset({"напомнить"}), person=name),
                       note="слово типа «напоминание»"))
        add(SearchCase("действие + человек", f"вопросы для {pf[GEN]}",
                       Need(person=name, subjects=frozenset({"вопросы"}))))

    # Синонимы, сокращения, разговорное — найти можно только по смыслу.
    meaning = [
        ("КП", Need(subjects=frozenset({"коммерческое предложение"}))),
        ("коммерческое", Need(subjects=frozenset({"коммерческое предложение"}))),
        ("ТЗ", Need(subjects=frozenset({"техническое задание"}))),
        ("техзадание", Need(subjects=frozenset({"техническое задание"}))),
        ("мобилка", Need(subjects=frozenset({"мобильное приложение"}))),
        ("приложение для телефона", Need(subjects=frozenset({"мобильное приложение"}))),
        ("презентуха", Need(subjects=frozenset({"презентация"}))),
        ("доклад", Need(subjects=frozenset({"отчёт"}))),
        ("смета расходов", Need(subjects=frozenset({"смета"}))),
        ("контракт", Need(subjects=frozenset({"договор"}))),
        ("финансы", Need(subjects=frozenset({"бюджет"}))),
        ("веб-сайт", Need(subjects=frozenset({"сайт"}))),
        ("созвониться с Севером", Need(actions=frozenset({"созвон"}), company="Север")),
        ("переговоры с Альфой", Need(actions=frozenset({"созвон"}), company="Альфа")),
        ("встретиться с Марией", Need(actions=frozenset({"встреча"}), person="Мария")),
        ("набрать Ивана", Need(actions=frozenset({"позвонить"}), person="Иван")),
        ("показ проекта", Need(actions=frozenset({"демо"}))),
        ("летучка", Need(actions=frozenset({"планёрка"}))),
        ("совещание по CRM", Need(actions=frozenset({"планёрка", "встреча"}),
                                  subjects=frozenset({"CRM"}))),
        ("отзывы по бюджету", Need(subjects=frozenset({"обратная связь", "бюджет"}))),
        ("дедлайны по сайту", Need(subjects=frozenset({"сроки", "сайт"}))),
    ]
    for query, need in meaning:
        add(SearchCase("синонимы и сокращения", query, need))

    # Опечатки в имени, компании, теме: одна буква.
    for name, pf in PEOPLE.items():
        add(SearchCase("опечатка", _typo(pf[NOM], rng), Need(person=name), note=pf[NOM]))
        add(SearchCase("опечатка", f"позвонить {_typo(pf[DAT], rng)}",
                       Need(actions=frozenset({"позвонить"}), person=name), note=pf[DAT]))
    for name, cf in COMPANIES.items():
        add(SearchCase("опечатка", f"созвон с {_typo(cf[2], rng)}",
                       Need(actions=frozenset({"созвон"}), company=name), note=cf[2]))
    for topic, tf in TOPICS.items():
        if topic != "CRM":
            add(SearchCase("опечатка", _typo(tf[NOM].split()[-1], rng),
                           Need(subjects=frozenset({topic})), note=tf[NOM]))

    # Речь: нижний регистр, без знаков, слова-паразиты (так текст отдаёт распознавание).
    speech = [
        ("ну встреча с марией по хакатону", Need(actions=frozenset({"встреча"}), person="Мария",
                                                 subjects=frozenset({"хакатон"}))),
        ("короче созвон с севером", Need(actions=frozenset({"созвон"}), company="Север")),
        ("эту как её смету", Need(subjects=frozenset({"смета"}))),
        ("типа отчет", Need(subjects=frozenset({"отчёт"}))),
        ("вот это демо по сайту", Need(actions=frozenset({"демо"}), subjects=frozenset({"сайт"}))),
        ("с этим с дмитрием по бюджету", Need(person="Дмитрий", subjects=frozenset({"бюджет"}))),
        ("ммм позвонить ольге", Need(actions=frozenset({"позвонить"}), person="Ольга")),
        ("пульс", Need(company="Пульс")),
        ("наталья crm", Need(person="Наталья", subjects=frozenset({"CRM"}))),
        ("планерка по crm", Need(actions=frozenset({"планёрка"}), subjects=frozenset({"CRM"}))),
        ("СРМ", Need(subjects=frozenset({"CRM"}))),  # кириллицей
        ("коммерческое предложение для алексея",
         Need(person="Алексей", subjects=frozenset({"коммерческое предложение"}))),
    ]
    for query, need in speech:
        add(SearchCase("речь и паразиты", query, need))

    # Несуществующее: люди, компании, темы, бытовое — ответа нет.
    nothing = Need(nothing=True)
    for query in ("дизайнер", "встреча с дизайнером", "созвон с юристами", "бухгалтер",
                  "позвонить Петру", "встреча с Виктором", "созвон с Яндексом", "Газпром",
                  "отпуск", "купить молоко", "ремонт машины", "день рождения мамы",
                  "стоматолог", "тренировка", "кино", "аквапарк", "налоги", "логотип",
                  "собеседование", "переезд"):
        add(SearchCase("несуществующее", query, nothing))

    # Фильтры: тип (как поставит агент) и период — до сравнения текста.
    meetings = SearchFilters(types=[RecordType.MEETING])
    tasks = SearchFilters(types=[RecordType.TASK, RecordType.REMINDER])
    past = SearchFilters(date_to=now)
    future = SearchFilters(date_from=now)
    for name, pf in PEOPLE.items():
        add(SearchCase("фильтр: только встречи", pf[NOM], Need(person=name), meetings))
        add(SearchCase("фильтр: только задачи", pf[NOM], Need(person=name), tasks))
        add(SearchCase("фильтр: прошлое", pf[NOM], Need(person=name), past))
        add(SearchCase("фильтр: будущее", pf[NOM], Need(person=name), future))
    for topic, tf in TOPICS.items():
        add(SearchCase("фильтр: только встречи", tf[NOM], Need(subjects=frozenset({topic})),
                       meetings))
        month = SearchFilters(date_from=now, date_to=now + timedelta(days=30))
        add(SearchCase("фильтр: ближайший месяц", tf[NOM], Need(subjects=frozenset({topic})),
                       month))

    # Пустые и странные запросы: значимых слов нет — ответа нет.
    for query in ("", "   ", "с по про", "и", "123", "2026", "?!", "а а а а"):
        add(SearchCase("пустое и странное", query, nothing))
    add(SearchCase("пустое и странное", "встреча", Need(actions=frozenset({"встреча"})),
                   note="одно слово типа"))
    add(SearchCase("пустое и странное", "встреча с Марией по хакатону " * 5,
                   Need(actions=frozenset({"встреча"}), person="Мария",
                        subjects=frozenset({"хакатон"})), note="повтор ×5"))
    add(SearchCase("пустое и странное", "crm", Need(subjects=frozenset({"CRM"})),
                   note="латиница строчными"))
    return out


# ---------- цели изменения ----------

def _phrase(c: Concepts) -> str | None:
    """Как пользователь назовёт запись в команде («перенеси …», «отмени …»)."""
    pf = PEOPLE.get(c.person) if c.person else None
    cf = COMPANIES.get(c.company) if c.company else None
    topic = next((s for s in c.subjects if s in TOPICS), None)
    doc = next((s for s in c.subjects if s in DOCUMENTS and s not in TOPICS), None)
    tf = TOPICS.get(topic) if topic else None
    if c.action == "встреча":
        return f"встречу с {pf[INS]} по {tf[1]}"
    if c.action == "созвон":
        return f"созвон с {cf[2]} по {tf[1]}"
    if c.action == "позвонить":
        return f"позвонить {pf[DAT]}"
    if c.action == "напомнить":
        return f"напоминание {pf[DAT]} про {tf[2]}"
    if c.action == "демо":
        return f"демо по {tf[1]}"
    if c.action == "планёрка":
        return f"планёрку по {tf[1]}"
    if c.action == "подготовиться":
        return f"подготовиться к встрече с {cf[2]}"
    if c.action == "отправить" and pf and doc:
        return f"отправить {DOCUMENTS[doc][1]} {pf[DAT]}"
    if c.action == "согласовать" and pf:
        return f"согласовать {DOCUMENTS[next(iter(c.subjects))][1]} с {pf[INS]}"
    if c.action == "обсудить" and pf and tf:
        return f"обсудить {tf[2]} с {pf[INS]}"
    return None


def _need_of(c: Concepts, phrase_says_meeting: bool) -> Need:
    return Need(
        actions=frozenset({c.action}),
        person=c.person,
        company=c.company,
        subjects=c.subjects,
        types=frozenset({RecordType.MEETING}) if phrase_says_meeting else frozenset(),
    )


def target_cases(records, now: datetime, seed: int = 20261029) -> list[TargetCase]:
    """`records` — записи пользователя (schemas.Record) после загрузки датасета."""
    rng = random.Random(seed)
    tz = now.tzinfo
    active = [r for r in records if r.status == RecordStatus.ACTIVE]
    done = [r for r in records if r.status == RecordStatus.DONE]
    by_title: dict[str, list] = {}
    for r in active:
        by_title.setdefault(r.title, []).append(r)
    out: list[TargetCase] = []
    add = out.append

    for title, rows in sorted(by_title.items()):
        c = parse_title(title)
        phrase = _phrase(c)
        if phrase is None:
            continue
        says_meeting = phrase.startswith(("встречу", "созвон"))
        need = _need_of(c, says_meeting)
        group = "одна запись" if len(rows) == 1 else "несколько записей"
        add(TargetCase(group, phrase, need))

        first = min(rows, key=lambda r: r.start)
        local = first.start.astimezone(tz)
        add(TargetCase("с днём и временем", phrase, need, when=local, when_kind="datetime"))
        add(TargetCase("с днём", phrase, need,
                       when=local.replace(hour=0, minute=0, second=0, microsecond=0),
                       when_kind="date"))
        # День, когда такой записи нет: «перенеси … в среду», а она в пятницу.
        days = {r.start.astimezone(tz).date() for r in rows}
        wrong = local + timedelta(days=rng.choice((1, 2, 3, 5, 9)))
        while wrong.date() in days:
            wrong += timedelta(days=1)
        add(TargetCase("с чужим днём", phrase, need,
                       when=wrong.replace(hour=0, minute=0, second=0, microsecond=0),
                       when_kind="date", note="подходящих нет: не исполнять"))

    # Сочетания, которых среди активных нет: «встречу с Сергеем по хакатону».
    present = {(parse_title(t).person, s) for t in by_title
               if parse_title(t).action == "встреча" for s in parse_title(t).subjects}
    for name, pf in PEOPLE.items():
        for topic, tf in TOPICS.items():
            if (name, topic) in present:
                continue
            add(TargetCase("сочетания нет", f"встречу с {pf[INS]} по {tf[1]}",
                           Need(actions=frozenset({"встреча"}), person=name,
                                subjects=frozenset({topic}),
                                types=frozenset({RecordType.MEETING}))))

    # «Встречу» там, где с этим человеком и темой есть только задача или напоминание:
    # пользователь назвал встречу — задачу менять нельзя.
    task_pairs = {(parse_title(t).person, s) for t in by_title
                  if parse_title(t).action in ("обсудить", "напомнить") and parse_title(t).person
                  for s in parse_title(t).subjects if s in TOPICS}
    for name, topic in sorted(task_pairs - present):
        pf, tf = PEOPLE[name], TOPICS[topic]
        add(TargetCase("«встречу», а есть только задача", f"встречу с {pf[INS]} по {tf[1]}",
                       Need(actions=frozenset({"встреча"}), person=name,
                            subjects=frozenset({topic}), types=frozenset({RecordType.MEETING}))))

    # «Верни» и «не выполнено» — среди выполненных.
    done_titles: dict[str, list] = {}
    for r in done:
        done_titles.setdefault(r.title, []).append(r)
    statuses = [RecordStatus.DONE, RecordStatus.CANCELLED]
    for title, rows in sorted(done_titles.items())[::4]:
        c = parse_title(title)
        phrase = _phrase(c)
        if phrase is None:
            continue
        last = max(rows, key=lambda r: r.start).start.astimezone(tz)
        add(TargetCase("среди выполненных (с днём и временем)", phrase,
                       _need_of(c, phrase.startswith(("встречу", "созвон"))),
                       when=last, when_kind="datetime", statuses=statuses))

    # Без описания: «отмени всё на этот день» — все записи дня по фильтру.
    for r in sorted(active, key=lambda r: r.start)[::40]:
        day = r.start.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        add(TargetCase("без описания: весь день", None, Need(),
                       filters=SearchFilters(date_from=day, date_to=day + timedelta(days=1)),
                       note=f"{day:%d.%m.%Y}"))
    return out
