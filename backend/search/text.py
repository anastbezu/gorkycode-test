"""Уровень «точно»: есть ли в названии записи каждое значимое слово запроса.

Правило контракта (`docs/contracts/search.md`, «Общие правила»), алгоритм — из замера
техлида на нашем датасете (docs/modules/search.md): слово запроса совпадает со словом
названия, если у них одна основа
(Snowball russian: «юристами» ↔ «юристом») или слова почти одинаковые
(`rapidfuzz.fuzz.ratio ≥ 85`: искажённый падеж в датасете «Позвонить Дмитрием», опечатка).

Почему не полнотекст Postgres: Snowball сам по себе не сводит падежи имён
(«Иван» → `ива`, «Иваном» → `иван`), нужен второй критерий — почти совпадающее слово.
«Каждое слово по основе ИЛИ почти совпадает» в SQL громоздко, а записей у пользователя
около тысячи — сравнение в Python занимает миллисекунды.
"""

import re

import snowballstemmer
from rapidfuzz import fuzz

# Слова — буквы и цифры: «CRM», «1С», «ТЗ» остаются словами.
WORD = re.compile(r"[0-9a-zа-я]+")

# Почти совпадающее слово: порог из замера на датасете (опечатка, «Ольге» ~ «Ольгой»).
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


def stem(word: str) -> str:
    return _STEMMER.stemWord(word)


# Слова типа записи («задачу», «напоминание», «встречу», «дело») — по основе.
# Контракт: они значимы, только если есть в названии («Встреча с Иваном»); в названиях задач
# слова «задача» нет, поэтому «задачу про смету» ищется как «смету».
TYPE_WORD_STEMS = frozenset(stem(w) for w in ("задача", "напоминание", "встреча", "дело"))


def words(text: str) -> list[str]:
    """Слова текста в нижнем регистре; «ё» → «е» («отчет» и «отчёт» — одно слово)."""
    return WORD.findall(text.lower().replace("ё", "е"))


class QueryWords:
    """Значимые слова запроса, разобранные один раз на весь перебор записей."""

    def __init__(self, query: str):
        significant = [w for w in words(query) if w not in STOP_WORDS]
        self.required = [(w, stem(w)) for w in significant if stem(w) not in TYPE_WORD_STEMS]
        self.type_words = [(w, stem(w)) for w in significant if stem(w) in TYPE_WORD_STEMS]



class TitleWords:
    """Слова названия записи: сами слова (для нечёткого сравнения) и их основы."""

    def __init__(self, title: str):
        self.words = [w for w in words(title) if w not in STOP_WORDS]
        self.stems = {stem(w) for w in self.words}

    def has(self, word: str, word_stem: str) -> bool:
        if word_stem in self.stems:
            return True
        return any(fuzz.ratio(word, w) >= FUZZY_WORD_MIN_RATIO for w in self.words)


def is_exact(query: QueryWords, title: TitleWords) -> bool:
    """Уровень «точно»: каждое значимое слово запроса есть в названии.

    Слово типа записи отбрасывается, если в названии его нет: «встречу с Иваном»
    совпадает с «Встреча с Иваном» и с «Созвон с Иваном», но не с «Встреча с Ольгой».
    Если после этого значимых слов не осталось («встречу» и название «Созвон с Иваном») —
    совпадения нет: пустой запрос не совпадает ни с чем.
    """
    type_words_in_title = [s for _, s in query.type_words if s in title.stems]
    if not query.required and not type_words_in_title:
        return False
    return all(title.has(w, s) for w, s in query.required)
