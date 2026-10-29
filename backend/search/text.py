"""Уровень «точно»: есть ли в названии записи каждое значимое слово запроса.

Правило контракта (`docs/contracts/search.md`, «Общие правила»), алгоритм — из замера
техлида на нашем датасете (docs/modules/search.md). Слово запроса совпадает со словом
названия, если выполнено одно из трёх:
- одна основа — Snowball russian отрезает окончания по правилам: «юристами» ↔ «юристом»;
- одна словарная форма — pymorphy3 знает формы слов по словарю: «Сергею» ↔ «Сергеем»
  (основы у них разные: `серг` и `серге`), «Иван» ↔ «Иваном»;
- слова почти одинаковые по буквам — `rapidfuzz.fuzz.ratio ≥ 85` — только если хотя бы одно
  из них не словарное, то есть это опечатка («Дмтрий» ↔ «Дмитрий»). Два словарных слова
  с разными словарными формами — разные слова, даже если отличаются одной буквой:
  «Виктором» ↔ «Вектором» (ratio 88) не совпадают.

Почему не полнотекст Postgres: он сравнивает только основы Snowball, а они не сводят падежи
имён. «Каждое слово по основе, словарной форме или почти по буквам» в SQL не выразить,
а записей у пользователя около тысячи — сравнение в Python занимает миллисекунды.
"""

import re
from functools import lru_cache

import pymorphy3
import snowballstemmer
from rapidfuzz import fuzz

from schemas import RecordType

# Слова — буквы и цифры: «CRM», «1С», «ТЗ» остаются словами.
WORD = re.compile(r"[0-9a-zа-я]+")

# Почти совпадающее слово: порог из замера на датасете (опечатка, «Ольге» ~ «Ольгой»).
# Мягче нельзя: «созвон с Севером по CRM» не должен совпадать с «…по новому продукту».
FUZZY_WORD_MIN_RATIO = 85

# Служебные слова — список Postgres `russian` (snowball russian.stop).
STOP_WORDS = frozenset(
    """и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только
ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был
него до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней
для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того
потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем
всех никогда можно при наконец два об другой хоть после над больше тот через эти нас про всего
них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя
такой им более всегда конечно всю между""".split()
)

_STEMMER = snowballstemmer.stemmer("russian")
_MORPH = pymorphy3.MorphAnalyzer()


def stem(word: str) -> str:
    return _STEMMER.stemWord(word)


@lru_cache(maxsize=50_000)
def lemmas(word: str) -> frozenset[str]:
    """Словарные формы слова. У омонимов их несколько: «стали» — «сталь» и «стать»."""
    return frozenset(p.normal_form.replace("ё", "е") for p in _MORPH.parse(word))


@lru_cache(maxsize=50_000)
def is_dictionary_word(word: str) -> bool:
    """Слово есть в словаре pymorphy3, а не угадано по окончанию.

    «Вектором» — есть, «Дмтрий» — нет.
    """
    return _MORPH.word_is_known(word)


# Слова типа записи — по основе: какой тип записи называет слово (контракт search.md,
# «Общие правила»). «Задачи» — task и reminder, как у агента (`TYPES_HINT` в
# schemas/actions.py); «дело» — любой тип.
TYPE_WORDS = {
    stem("встреча"): frozenset({RecordType.MEETING}),
    stem("задача"): frozenset({RecordType.TASK, RecordType.REMINDER}),
    stem("напоминание"): frozenset({RecordType.REMINDER}),
    stem("дело"): frozenset(RecordType),
}
TYPE_WORD_STEMS = frozenset(TYPE_WORDS)


def words(text: str) -> list[str]:
    """Слова текста в нижнем регистре; «ё» → «е» («отчет» и «отчёт» — одно слово)."""
    return WORD.findall(text.lower().replace("ё", "е"))


class Word:
    """Слово с основой и словарными формами — считаются один раз."""

    __slots__ = ("text", "stem", "lemmas", "in_dictionary")

    def __init__(self, text: str):
        self.text = text
        self.stem = stem(text)
        self.lemmas = lemmas(text)
        self.in_dictionary = is_dictionary_word(text)


class QueryWords:
    """Значимые слова запроса, разобранные один раз на весь перебор записей."""

    def __init__(self, query: str):
        significant = [Word(w) for w in words(query) if w not in STOP_WORDS]
        self.required = [w for w in significant if w.stem not in TYPE_WORD_STEMS]
        self.type_words = [w for w in significant if w.stem in TYPE_WORD_STEMS]


class TitleWords:
    """Значимые слова названия записи."""

    def __init__(self, title: str):
        self.words = [Word(w) for w in words(title) if w not in STOP_WORDS]
        self.stems = {w.stem for w in self.words}

    def has(self, word: Word) -> bool:
        if word.stem in self.stems:
            return True
        return any(word.lemmas & w.lemmas or _typo_of(word, w) for w in self.words)


def _typo_of(a: Word, b: Word) -> bool:
    """Одно слово — опечатка в другом: буквы почти те же, и хотя бы одно не словарное."""
    if a.in_dictionary and b.in_dictionary:
        return False
    return fuzz.ratio(a.text, b.text) >= FUZZY_WORD_MIN_RATIO


def is_exact(query: QueryWords, title: TitleWords, record_type: RecordType) -> bool:
    """Уровень «точно»: каждое значимое слово запроса есть в названии.

    Слово типа записи («встречу», «задачу») совпадает, если оно есть в названии или если
    запись этого типа: «встречу с Иваном» совпадает с «Встреча с Иваном» и с «Созвон
    с Иваном» (тип — встреча), но не с задачей «Позвонить Иваном». Иначе «отмени встречу
    с Алексеем по CRM» отменило бы задачу «Обсудить CRM с Алексеем».
    Запрос без значимых слов («с по про») не совпадает ни с чем.
    """
    if not query.required and not query.type_words:
        return False
    if not all(title.has(w) for w in query.required):
        return False
    return all(
        w.stem in title.stems or record_type in TYPE_WORDS[w.stem] for w in query.type_words
    )
