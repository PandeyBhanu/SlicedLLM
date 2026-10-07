"""Token-aware diff of two texts.

Algorithm
---------
1. Tokenize both texts into `DiffUnit`s (BPE tokens fused at UTF-8 boundaries).
2. Small inputs (<= FULL_DIFF_MAX_UNITS units per side): run `difflib.SequenceMatcher`
   (autojunk disabled) directly on the unit sequences.
3. Large inputs: SequenceMatcher is quadratic in the worst case, so first diff *lines* to find
   unchanged anchors, then token-diff only the changed hunks (hierarchical diff). A hunk that is
   still too large is emitted as one coarse delete+insert and the result is flagged `coarse`.
4. Adjacent operations of the same kind are merged; a "replace" becomes delete + insert.

Invariant (tested): concatenating `equal`+`delete` segment text yields the original; `equal`+
`insert` yields the modified text.
"""

import difflib
import html
from dataclasses import dataclass, field
from typing import Literal

from app.core.exceptions import ValidationError
from app.diff.tokenizers import DiffUnit, Tokenizer, get_tokenizer

Op = Literal["equal", "insert", "delete"]

FULL_DIFF_MAX_UNITS = 4000
HUNK_MAX_UNITS = 6000
MAX_INPUT_BYTES = 2 * 1024 * 1024  # per text


@dataclass
class DiffSegment:
    op: Op
    text: str
    token_count: int


@dataclass
class DiffResult:
    granularity: str  # "token" | "line" | "char"
    tokenizer: str
    approximate_tokenizer: bool
    algorithm: str  # "sequence-matcher" | "line-anchored"
    coarse: bool
    original_units: int
    modified_units: int
    original_tokens: int
    modified_tokens: int
    segments: list[DiffSegment] = field(default_factory=list)

    @property
    def stats(self) -> dict[str, float]:
        added = sum(s.token_count for s in self.segments if s.op == "insert")
        removed = sum(s.token_count for s in self.segments if s.op == "delete")
        same = sum(s.token_count for s in self.segments if s.op == "equal")
        total = 2 * same + added + removed
        return {
            "added": added,
            "removed": removed,
            "unchanged": same,
            "similarity": (2 * same / total) if total else 1.0,
        }

    @property
    def original_text(self) -> str:
        return "".join(s.text for s in self.segments if s.op != "insert")

    @property
    def modified_text(self) -> str:
        return "".join(s.text for s in self.segments if s.op != "delete")

    def to_safe_html(self) -> str:
        """HTML-escaped rendering for any server-side consumer. Content is never interpolated
        raw."""
        cls = {"equal": "diff-equal", "insert": "diff-added", "delete": "diff-removed"}
        return "".join(
            f'<span class="{cls[s.op]}">{html.escape(s.text, quote=True)}</span>'
            for s in self.segments
        )

    def to_dict(self) -> dict:
        return {
            "granularity": self.granularity,
            "tokenizer": self.tokenizer,
            "approximate_tokenizer": self.approximate_tokenizer,
            "algorithm": self.algorithm,
            "coarse": self.coarse,
            "original_units": self.original_units,
            "modified_units": self.modified_units,
            "original_tokens": self.original_tokens,
            "modified_tokens": self.modified_tokens,
            "stats": self.stats,
            "segments": [
                {"op": s.op, "text": s.text, "token_count": s.token_count} for s in self.segments
            ],
        }


def _join(units: list[DiffUnit]) -> tuple[str, int]:
    return b"".join(u.data for u in units).decode("utf-8", errors="replace"), sum(
        u.token_count for u in units
    )


def _opcodes(a: list[DiffUnit], b: list[DiffUnit]):
    matcher = difflib.SequenceMatcher(
        None, [u.data for u in a], [u.data for u in b], autojunk=False
    )
    return matcher.get_opcodes()


def _emit(out: list[tuple[Op, list[DiffUnit]]], op: Op, units: list[DiffUnit]) -> None:
    if not units:
        return
    if out and out[-1][0] == op:
        out[-1][1].extend(units)
    else:
        out.append((op, list(units)))


def _diff_units(a: list[DiffUnit], b: list[DiffUnit], out: list[tuple[Op, list[DiffUnit]]]) -> bool:
    """Diff two unit lists directly. Returns True if the result was coarse."""
    if len(a) > HUNK_MAX_UNITS or len(b) > HUNK_MAX_UNITS:
        _emit(out, "delete", a)
        _emit(out, "insert", b)
        return True
    for tag, i1, i2, j1, j2 in _opcodes(a, b):
        if tag == "equal":
            _emit(out, "equal", a[i1:i2])
        else:
            _emit(out, "delete", a[i1:i2])
            _emit(out, "insert", b[j1:j2])
    return False


def diff_texts(
    original: str,
    modified: str,
    *,
    granularity: Literal["token", "line", "char"] = "token",
    tokenizer: Tokenizer | None = None,
    model: str | None = None,
    provider: str | None = None,
    tokenizer_name: str | None = None,
) -> DiffResult:
    if (
        len(original.encode("utf-8")) > MAX_INPUT_BYTES
        or len(modified.encode("utf-8")) > MAX_INPUT_BYTES
    ):
        raise ValidationError(f"Diff inputs are limited to {MAX_INPUT_BYTES} bytes each")

    if granularity == "line":
        tok = get_tokenizer(name="line")
    elif granularity == "char":
        tok = get_tokenizer(name="char")
    else:
        tok = tokenizer or get_tokenizer(model=model, provider=provider, name=tokenizer_name)

    a_units = tok.units(original)
    b_units = tok.units(modified)
    parts: list[tuple[Op, list[DiffUnit]]] = []
    coarse = False
    algorithm = "sequence-matcher"

    if max(len(a_units), len(b_units)) <= FULL_DIFF_MAX_UNITS or granularity == "line":
        coarse = _diff_units(a_units, b_units, parts)
    else:
        algorithm = "line-anchored"
        line_tok = get_tokenizer(name="line")
        a_lines = line_tok.units(original)
        b_lines = line_tok.units(modified)
        for tag, i1, i2, j1, j2 in _opcodes(a_lines, b_lines):
            a_text = b"".join(u.data for u in a_lines[i1:i2]).decode("utf-8")
            b_text = b"".join(u.data for u in b_lines[j1:j2]).decode("utf-8")
            if tag == "equal":
                _emit(parts, "equal", tok.units(a_text))
            else:
                coarse |= _diff_units(tok.units(a_text), tok.units(b_text), parts)

    segments = []
    for op, units in parts:
        text, count = _join(units)
        segments.append(DiffSegment(op=op, text=text, token_count=count))

    return DiffResult(
        granularity=granularity,
        tokenizer=tok.name,
        approximate_tokenizer=tok.approximate,
        algorithm=algorithm,
        coarse=coarse,
        original_units=len(a_units),
        modified_units=len(b_units),
        original_tokens=sum(u.token_count for u in a_units),
        modified_tokens=sum(u.token_count for u in b_units),
        segments=segments,
    )
