"""Small, dependency-free statistics helpers for benchmark aggregation."""

from __future__ import annotations

import math
from collections.abc import Sequence


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def stddev(values: Sequence[float]) -> float | None:
    """Sample standard deviation (n-1); ``None`` for fewer than two values."""
    if len(values) < 2:
        return None
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a binomial proportion.

    Preferred over the normal approximation because benchmark sample sizes
    are small and pass rates are often near 0 or 1.
    """
    if trials == 0:
        return None
    p = successes / trials
    denom = 1 + z**2 / trials
    centre = (p + z**2 / (2 * trials)) / denom
    margin = z * math.sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def rounded(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)
