import time

import pytest
import tiktoken

from app.core.exceptions import ValidationError
from app.diff import diff_texts, get_tokenizer
from app.diff.engine import FULL_DIFF_MAX_UNITS, MAX_INPUT_BYTES
from tests.helpers import create_prompt_with_versions


def roundtrip(a: str, b: str, **kw):
    d = diff_texts(a, b, **kw)
    assert d.original_text == a, "equal+delete segments must rebuild the original"
    assert d.modified_text == b, "equal+insert segments must rebuild the modified text"
    return d


def ops(d):
    return [(s.op, s.text) for s in d.segments]


def test_uses_real_bpe_tokens_not_whitespace_words():
    tok = get_tokenizer(name="cl100k_base")
    text = "Hello,world!How's it going?"
    assert len(text.split()) == 3  # the old whitespace "tokens"
    enc = tiktoken.get_encoding("cl100k_base")
    assert sum(u.token_count for u in tok.units(text)) == len(enc.encode(text)) > 3


def test_identical_texts_are_one_equal_segment():
    d = roundtrip("same prompt", "same prompt")
    assert ops(d) == [("equal", "same prompt")] and d.stats["similarity"] == 1.0


def test_both_empty_and_one_empty():
    assert roundtrip("", "").segments == []
    assert ops(roundtrip("", "new")) == [("insert", "new")]
    assert ops(roundtrip("old", "")) == [("delete", "old")]


def test_insertion_deletion_and_replacement():
    d = roundtrip("You are a helpful assistant.", "You are a concise assistant today.")
    kinds = {s.op for s in d.segments}
    assert kinds == {"equal", "insert", "delete"}
    assert any("helpful" in s.text for s in d.segments if s.op == "delete")
    assert any("concise" in s.text for s in d.segments if s.op == "insert")
    assert d.stats["added"] > 0 and d.stats["removed"] > 0 and 0 < d.stats["similarity"] < 1


def test_punctuation_only_change_is_localised():
    d = roundtrip("Answer in JSON, please.", "Answer in JSON; please!")
    changed = "".join(s.text for s in d.segments if s.op != "equal")
    assert set(changed) <= set(",;.!") and changed
    assert "".join(s.text for s in d.segments if s.op == "equal").startswith("Answer in JSON")


def test_whitespace_changes_are_visible_and_lossless():
    d = roundtrip("a b", "a  b")  # whitespace words would call these identical
    assert any(s.op != "equal" for s in d.segments)
    d = roundtrip("line1\nline2", "line1\r\nline2\t")
    assert any(s.op != "equal" for s in d.segments)
    roundtrip("   leading", "leading   ")


def test_unicode_and_emoji_survive_even_when_bpe_splits_characters():
    for a, b in [
        ("Bonjour le monde", "Bonjour, le monde 🌍"),
        ("日本語のプロンプト", "日本語のシステムプロンプト"),
        ("café ☕", "cafe ☕"),
        ("👨‍👩‍👧 family", "👨‍👩‍👦 family"),
        ("naïve", "naive"),
    ]:
        d = roundtrip(a, b)
        assert "\ufffd" not in "".join(s.text for s in d.segments)


def test_multiline_prompt_diff():
    a = "System: be brief.\nUser: {{input}}\nAssistant:"
    b = "System: be brief and kind.\nUser: {{input}}\nRules:\n- cite sources\nAssistant:"
    d = roundtrip(a, b)
    inserted = "".join(s.text for s in d.segments if s.op == "insert")
    assert "kind" in inserted and "cite sources" in inserted and "Rules" in inserted


def test_repeated_tokens():
    d = roundtrip("the the the the", "the the the the the the")
    assert d.stats["removed"] == 0 and d.stats["added"] > 0
    d = roundtrip("ab ab ab", "ab ab")
    assert d.stats["added"] == 0 and d.stats["removed"] > 0
    roundtrip("x" * 500, "x" * 499 + "y")


def test_special_token_text_is_treated_as_plain_text():
    roundtrip("end <|endoftext|> here", "end <|endoftext|> there")


def test_granularities_are_distinct_and_labelled():
    a, b = "The quick brown fox", "The quick red fox"
    token, line, char = (roundtrip(a, b, granularity=g) for g in ("token", "line", "char"))
    assert (token.granularity, line.granularity, char.granularity) == ("token", "line", "char")
    assert ops(line) == [("delete", a), ("insert", b)]  # a one-line change replaces the whole line
    assert char.original_units == len(a) and token.original_tokens < char.original_units
    assert (
        token.tokenizer == "cl100k_base" and line.tokenizer == "line" and char.tokenizer == "char"
    )


def test_tokenizer_is_selected_from_model_family():
    assert get_tokenizer(model="gpt-4o").name == "o200k_base"
    assert get_tokenizer(model="gpt-4-turbo").name == "cl100k_base"
    assert get_tokenizer(model="gpt-3.5-turbo").name == "cl100k_base"
    llama = get_tokenizer(model="llama3-8b-8192", provider="groq")
    assert llama.name == "cl100k_base" and llama.approximate is True
    assert get_tokenizer(model="gpt-4o").approximate is False
    assert get_tokenizer(name="o200k_base").name == "o200k_base"
    d = diff_texts("a b c", "a b d", model="gpt-4o")
    assert d.tokenizer == "o200k_base"
    with pytest.raises(ValueError):
        get_tokenizer(name="no-such-encoding")


def test_html_rendering_escapes_content():
    d = roundtrip('<script>alert("x")</script> hi', "<img src=x onerror=alert(1)> hi & bye")
    html = d.to_safe_html()
    assert "<script>" not in html and "<img" not in html and "&lt;script&gt;" in html
    assert html.count("<span") == len(d.segments)


def test_long_prompt_uses_line_anchored_diff_and_stays_fast():
    lines = [f"Rule {i}: always answer concisely and cite source number {i}." for i in range(1500)]
    a = "\n".join(lines)
    b_lines = list(lines)
    b_lines[700] = "Rule 700: NEVER answer without a citation."
    b_lines.insert(1200, "Extra rule inserted here.")
    b = "\n".join(b_lines)
    started = time.perf_counter()
    d = roundtrip(a, b)
    assert time.perf_counter() - started < 15
    assert d.algorithm == "line-anchored" and d.original_units > FULL_DIFF_MAX_UNITS
    changed = "".join(s.text for s in d.segments if s.op != "equal")
    assert "NEVER" in changed and "Extra rule" in changed and len(changed) < 400
    assert d.coarse is False


def test_huge_single_hunk_degrades_to_coarse_but_stays_lossless():
    a = "start\n" + " ".join(f"w{i}" for i in range(9000)) + "\nend"
    b = "start\n" + " ".join(f"v{i}" for i in range(9000)) + "\nend"
    d = roundtrip(a, b)
    assert d.coarse is True and d.algorithm == "line-anchored"


def test_input_size_limit():
    with pytest.raises(ValidationError):
        diff_texts("a" * (MAX_INPUT_BYTES + 1), "b")


async def test_diff_endpoint_contract(client):
    prompt_id, (v1, v2) = await create_prompt_with_versions(
        client,
        templates=[
            ("1.0.0", "Summarize {{input}} briefly."),
            ("1.1.0", "Summarize {{input}} in {{style}} style."),
        ],
    )
    r = await client.get(
        f"/api/v1/prompts/{prompt_id}/diff", params={"version_a_id": v1, "version_b_id": v2}
    )
    assert r.status_code == 200
    body = r.json()
    assert (
        body["template_diff"]["granularity"] == "token"
        and body["template_diff"]["tokenizer"] == "cl100k_base"
    )
    assert body["variables"] == {"added": ["style"], "removed": [], "unchanged": ["input"]}
    assert (
        "".join(s["text"] for s in body["template_diff"]["segments"] if s["op"] != "insert")
        == "Summarize {{input}} briefly."
    )
    assert body["version_a"]["id"] == v1 and body["version_b"]["id"] == v2
    r = await client.get(
        f"/api/v1/prompts/{prompt_id}/diff",
        params={"version_a_id": v1, "version_b_id": v2, "model": "gpt-4o"},
    )
    assert r.json()["template_diff"]["tokenizer"] == "o200k_base"
    bad = await client.get(
        f"/api/v1/prompts/{prompt_id}/diff",
        params={"version_a_id": v1, "version_b_id": v2, "tokenizer": "nope"},
    )
    assert bad.status_code == 400
    bad = await client.get(
        f"/api/v1/prompts/{prompt_id}/diff",
        params={"version_a_id": v1, "version_b_id": v2, "granularity": "word"},
    )
    assert bad.status_code == 422


async def test_changelog_reports_token_diff_between_consecutive_versions(client):
    prompt_id, _ = await create_prompt_with_versions(client)
    entries = (await client.get(f"/api/v1/prompts/{prompt_id}/changelog")).json()
    assert [e["semantic_version"] for e in entries] == ["1.0.0", "1.1.0"]
    assert entries[0]["diff_stats"] is None
    assert entries[1]["previous_version"] == "1.0.0" and entries[1]["diff_stats"]["added"] > 0
