"""CJK-aware tokenizer mirrored byte-for-byte in static/search.js.

Rule: lowercase everything; CJK ideographs (Unihan U+4E00–U+9FFF +
extension A U+3400–U+4DBF) emit one token per character; Latin
letters / digits / underscore form contiguous word tokens; everything
else is a token boundary. Empty input → empty list.

Mirror in JS lives in src/rednote_kb/site/static/search.js — both
sides MUST tokenize identically or recall breaks.
"""
from __future__ import annotations


def is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF


def is_word(ch: str) -> bool:
    cp = ord(ch)
    if 0x30 <= cp <= 0x39:       # 0-9
        return True
    if 0x61 <= cp <= 0x7A:       # a-z  (already lowered)
        return True
    if cp == 0x5F:               # _
        return True
    return False


def tokenize(s: str | None) -> list[str]:
    if not s:
        return []
    out: list[str] = []
    buf: list[str] = []
    for ch in s.lower():
        if is_cjk(ch):
            if buf:
                out.append("".join(buf))
                buf.clear()
            out.append(ch)
        elif is_word(ch):
            buf.append(ch)
        else:
            if buf:
                out.append("".join(buf))
                buf.clear()
    if buf:
        out.append("".join(buf))
    return out


def tokenize_unique(s: str | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tokenize(s):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out
