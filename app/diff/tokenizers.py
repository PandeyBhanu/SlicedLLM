"""Tokenizer layer for prompt diffs.

A `DiffUnit` is the smallest thing the diff compares. For model-token diffs a unit is one BPE
token, except that tokens which split a multi-byte UTF-8 character (byte-level BPE does this for
emoji / CJK) are fused back into one unit, so every unit is valid text and concatenating the
units of a document reproduces it byte-for-byte.

The tokenizer is selected from the model/provider. `tiktoken` only ships OpenAI vocabularies, so
for other model families (llama, mistral, gemma, ...) we use `cl100k_base` as an explicit,
labelled *approximation*: boundaries will not match the model's real tokens. Add a new entry to
`_FAMILY_RULES` (and a `Tokenizer` implementation) to support a native tokenizer.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import tiktoken

DEFAULT_ENCODING = "cl100k_base"


@dataclass(frozen=True)
class DiffUnit:
    data: bytes  # raw bytes of this unit (hashable, used for equality)
    token_count: int  # number of model tokens fused into this unit

    @property
    def text(self) -> str:
        return self.data.decode("utf-8", errors="replace")


class Tokenizer(Protocol):
    name: str
    approximate: bool

    def units(self, text: str) -> list[DiffUnit]: ...


def _fuse_units(token_bytes: list[bytes]) -> list[DiffUnit]:
    units: list[DiffUnit] = []
    buf = b""
    count = 0
    for tb in token_bytes:
        buf += tb
        count += 1
        try:
            buf.decode("utf-8")
        except UnicodeDecodeError:
            continue  # token split a multi-byte char; keep accumulating
        units.append(DiffUnit(buf, count))
        buf, count = b"", 0
    if buf:
        units.append(DiffUnit(buf, count))
    return units


@dataclass
class TiktokenTokenizer:
    name: str  # encoding name, e.g. "o200k_base"
    approximate: bool = False

    def __post_init__(self) -> None:
        self._enc = tiktoken.get_encoding(self.name)

    def units(self, text: str) -> list[DiffUnit]:
        if not text:
            return []
        # allowed_special="all": prompts may legitimately contain literal "<|endoftext|>".
        ids = self._enc.encode(text, allowed_special="all")
        return _fuse_units(self._enc.decode_tokens_bytes(ids))


@dataclass
class LineTokenizer:
    name: str = "line"
    approximate: bool = False

    def units(self, text: str) -> list[DiffUnit]:
        return [DiffUnit(line.encode("utf-8"), 1) for line in text.splitlines(keepends=True)]


@dataclass
class CharTokenizer:
    name: str = "char"
    approximate: bool = False

    def units(self, text: str) -> list[DiffUnit]:
        return [DiffUnit(ch.encode("utf-8"), 1) for ch in text]


# (substring of lowercase model name, encoding). First match wins.
_FAMILY_RULES = [
    ("gpt-4o", "o200k_base"),
    ("gpt-4.1", "o200k_base"),
    ("gpt-5", "o200k_base"),
    ("o1", "o200k_base"),
    ("o3", "o200k_base"),
    ("gpt-4", "cl100k_base"),
    ("gpt-3.5", "cl100k_base"),
    ("text-embedding", "cl100k_base"),
]


@lru_cache(maxsize=8)
def _tiktoken(name: str, approximate: bool) -> TiktokenTokenizer:
    return TiktokenTokenizer(name=name, approximate=approximate)


def get_tokenizer(
    *, model: str | None = None, provider: str | None = None, name: str | None = None
) -> Tokenizer:
    """Pick a tokenizer. Explicit `name` wins, then the model family, then a labelled fallback."""
    if name:
        if name == "line":
            return LineTokenizer()
        if name == "char":
            return CharTokenizer()
        return _tiktoken(name, False)  # raises ValueError for unknown encodings
    lowered = (model or "").lower()
    if provider in (None, "openai") or lowered.startswith(("gpt-", "o1", "o3")):
        for needle, encoding in _FAMILY_RULES:
            if needle in lowered:
                return _tiktoken(encoding, False)
    return _tiktoken(DEFAULT_ENCODING, provider not in (None, "openai") or bool(lowered))
