"""Run the JS tokenizer in Node and compare with the Python tokenizer.

If this drifts, search recall on the deployed site silently breaks.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from rednote_kb.index.tokenize import tokenize

JS_PATH = Path(__file__).resolve().parent.parent / "src" / "rednote_kb" / "site" / "static" / "search.js"

CASES = [
    "",
    "上海",
    "brunch",
    "Hello World",
    "iPhone 15 Pro Max 评测",
    "上海徐汇brunch推荐",
    "a.b,c",
    "上海，brunch！推荐",
    "hello_world",
    "中" * 50,
    "㐀abc",
    "a😀b",
    "こんにちは",
    "안녕",
    "  a   b  ",
    "1234567890",
    "MIXED上海case Test",
]


@pytest.fixture(scope="module")
def node_tokens() -> list[list[str]]:
    if not shutil.which("node"):
        pytest.skip("node not installed")

    # The browser script references `document`, `window`, etc. We strip the
    # browser-only bits and just exercise the tokenizer.
    src = JS_PATH.read_text("utf-8")
    # Extract the function bodies we need by name.
    needed = ["isCJK", "isWord", "tokenize"]
    runner = src.split("function escapeHtml")[0]  # everything above is pure logic

    cases_js = json.dumps(CASES, ensure_ascii=False)
    program = textwrap.dedent(f"""
        {runner}
        const cases = {cases_js};
        const out = cases.map(c => tokenize(c));
        process.stdout.write(JSON.stringify(out));
    """)

    res = subprocess.run(
        ["node", "-e", program],
        check=True, capture_output=True, text=True,
    )
    return json.loads(res.stdout)


def test_python_js_tokenizer_parity(node_tokens) -> None:
    for i, case in enumerate(CASES):
        py = tokenize(case)
        js = node_tokens[i]
        assert py == js, (
            f"tokenizer drift on case {i} {case!r}:\n  py = {py!r}\n  js = {js!r}"
        )
