"""Уровень «точно»: есть ли в названии записи каждое значимое слово запроса.

Правило контракта (`docs/contracts/search.md`, «Общие правила»), алгоритм — из замера
техлида на нашем датасете (docs/modules/search.md). Слово запроса совпадает со словом
названия, если выполнено одно из трёх:
- одна основа — Snowball russian отрезает окончания по правилам: «юристами» ↔ «юристом»;
- одна словарная форма — pymorphy3 знает формы слов по словарю: «Сергею» ↔ «Сергеем»
  (основы у них разные: `серг` и `серге`), «Иван» ↔ «Иваном»;
- слова почти одинаковые по буквам — `rapidfuzz.fuzz.ratio ≥ 85`: опечатка, искажённый
  падеж датасета («Ольге» ↔ «Ольгой»).

Почему не полнотекст Postgres: он сравнивает только основы Snowball, а они не сводят падежи
имён. «Каждое слово по основе, словарной форме или почти по буквам» в SQL не выразить,
а записей у пользователя около тысячи — сравнение в Python занимает миллисекунды.
"""

import re
from functools import lru_cache

import pymorphy3
import snowballstemmer
from rapidfuzz import fuzz

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


# Слова типа записи («задачу», «напоминание», «встречу», «дело») — по основе.
# Контракт: они значимы, только если есть в названии («Встреча с Иваном»); в названиях задач
# слова «задача» нет, поэтому «задачу про смету» ищется как «смету».
TYPE_WORD_STEMS = frozenset(stem(w) for w in ("задача", "напоминание", "встреча", "дело"))


def words(text: str) -> list[str]:
    """Слова текста в нижнем регистре; «ё» → «е» («отчет» и «отчёт» — одно слово)."""
    return WORD.findall(text.lower().replace("ё", "е"))


class Word:
    """Слово с основой и словарными формами — считаются один раз."""

    __slots__ = ("text", "stem", "lemmas")

    def __init__(self, text: str):
        self.text = text
        self.stem = stem(text)
        self.lemmas = lemmas(text)


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
        return any(
            word.lemmas & w.lemmas or fuzz.ratio(word.text, w.text) >= FUZZY_WORD_MIN_RATIO
            for w in self.words
        )


def is_exact(query: QueryWords, title: TitleWords) -> bool:
    """Уровень «точно»: каждое значимое слово запроса есть в названии.

    Слово типа записи отбрасывается, если в названии его нет: «встречу с Иваном»
    совпадает с «Встреча с Иваном» и с «Созвон с Иваном», но не с «Встреча с Ольгой».
    Если после этого значимых слов не осталось («встречу» и название «Созвон с Иваном») —
    совпадения нет: пустой запрос не совпадает ни с чем.
    """
    type_words_in_title = [w for w in query.type_words if w.stem in title.stems]
    if not query.required and not type_words_in_title:
        return False
    return all(title.has(w) for w in query.required)
