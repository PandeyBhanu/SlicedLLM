"""Aggregate statistics computed from persisted rows only (nothing is estimated or defaulted)."""

import math
from collections.abc import Sequence


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """95% Wilson score interval for a binomial proportion."""
    if n <= 0:
        return None, None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def criterion_means(rows: list[tuple[str, float, float]]) -> dict[str, tuple[float, float, int]]:
    acc: dict[str, list[tuple[float, float]]] = {}
    for name, a, b in rows:
        acc.setdefault(name, []).append((a, b))
    return {
        name: (sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v), len(v))
        for name, v in acc.items()
    }
