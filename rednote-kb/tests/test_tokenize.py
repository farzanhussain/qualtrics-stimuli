"""Tokenizer behaviour — MUST stay in lockstep with static/search.js."""
from __future__ import annotations

from rednote_kb.index.tokenize import tokenize, tokenize_unique


def test_empty_and_none() -> None:
    assert tokenize("") == []
    assert tokenize(None) == []
    assert tokenize_unique("") == []


def test_pure_cjk_one_token_per_char() -> None:
    assert tokenize("上海") == ["上", "海"]
    assert tokenize("北京东京") == ["北", "京", "东", "京"]


def test_pure_latin_word_run() -> None:
    assert tokenize("brunch") == ["brunch"]
    assert tokenize("Hello World") == ["hello", "world"]


def test_mixed_cjk_latin_digits() -> None:
    assert tokenize("iPhone 15 Pro Max 评测") == ["iphone", "15", "pro", "max", "评", "测"]
    assert tokenize("上海徐汇brunch推荐") == ["上", "海", "徐", "汇", "brunch", "推", "荐"]


def test_punctuation_is_boundary() -> None:
    assert tokenize("a.b,c") == ["a", "b", "c"]
    assert tokenize("上海，brunch！推荐") == ["上", "海", "brunch", "推", "荐"]
    # full-width punctuation
    assert tokenize("a　b") == ["a", "b"]  # ideographic space


def test_underscore_is_word_char() -> None:
    assert tokenize("hello_world") == ["hello_world"]


def test_dedup_preserves_order() -> None:
    assert tokenize_unique("上海上海brunch brunch") == ["上", "海", "brunch"]


def test_long_runs() -> None:
    out = tokenize("abcdefghij" * 100)
    assert out == ["abcdefghij" * 100]
    out = tokenize("中" * 50)
    assert out == ["中"] * 50


def test_extension_a_cjk_range() -> None:
    # U+3400 is the start of CJK Ext-A; '㐀' is the first ideograph.
    assert tokenize("㐀abc") == ["㐀", "abc"]


def test_non_cjk_non_word_unicode_dropped() -> None:
    # Hiragana, hangul, emoji — currently treated as boundaries.
    # If this changes, ALSO update static/search.js to match.
    assert tokenize("a😀b") == ["a", "b"]
    assert tokenize("こんにちは") == []
    assert tokenize("안녕") == []
