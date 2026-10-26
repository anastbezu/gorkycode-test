from services.search_stub import like_pattern, query_words


def test_query_words_drop_short_prepositions():
    assert query_words("созвон с юристами") == ["созвон", "юристами"]
    assert query_words("договор") == ["договор"]
    assert query_words("   ") == []


def test_like_pattern_escapes_wildcards():
    assert like_pattern("100%_x") == "%100\\%\\_x%"
