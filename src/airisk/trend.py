"""Pace of a series: doubling time or yearly gain, now against two years ago.

Every indicator is reduced to one question a reader can track the way they
track the Doomsday Clock: *is this moving faster or slower than it was?*

- Exponential series (compute, task length, money) are fitted as a straight
  line in log2 against time; the slope is doublings per year, reported as a
  doubling time in months.
- Bounded scores (percent of a benchmark solved) cannot double forever, so
  they are fitted as a straight line and reported in points per year.

The **recent** window is the last ``years`` up to the latest point; the
**prior** window is the same length immediately before it. The verdict
compares the two: accelerating when the recent pace is at least 25% faster,
slowing when it is at least 20% slower, steady between.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

Point = tuple[float, float]  # (decimal year, value)

MIN_POINTS = 3
FASTER = 1.25  # recent pace / prior pace at or above this = accelerating
SLOWER = 0.8  # at or below this = slowing


def year_of(d: date | str) -> float:
    """A date as a decimal year (2024-07-02 -> ~2024.5)."""
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    start = date(d.year, 1, 1)
    days = (date(d.year + 1, 1, 1) - start).days
    return d.year + (d - start).days / days


def date_of(y: float) -> date:
    yr = int(math.floor(y))
    start = date(yr, 1, 1)
    days = (date(yr + 1, 1, 1) - start).days
    return date.fromordinal(start.toordinal() + min(days - 1, int(round((y - yr) * days))))


def ols(points: Sequence[Point]) -> tuple[float, float] | None:
    """Least-squares slope and intercept, or None when the fit is undefined."""
    n = len(points)
    if n < 2:
        return None
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in points) / sxx
    return slope, my - slope * mx


def window(points: Iterable[Point], start: float, end: float) -> list[Point]:
    return [(x, y) for x, y in points if start < x <= end]


@dataclass
class Pace:
    """One window's fit. ``rate`` is doublings/year (log) or units/year (linear)."""

    rate: float
    intercept: float
    n: int
    start: float
    end: float

    @property
    def doubling_months(self) -> float | None:
        return 12.0 / self.rate if self.rate > 0 else None


def fit(points: Iterable[Point], start: float, end: float, log: bool) -> Pace | None:
    pts = window(points, start, end)
    if log:
        pts = [(x, math.log2(y)) for x, y in pts if y > 0]
    if len(pts) < MIN_POINTS:
        return None
    r = ols(pts)
    if r is None:
        return None
    return Pace(rate=r[0], intercept=r[1], n=len(pts), start=start, end=end)


def verdict(recent: Pace | None, prior: Pace | None) -> str:
    """accelerating / steady / slowing / reversing, or 'too little data'."""
    if recent is None or prior is None:
        return "too little data"
    if prior.rate <= 0:
        return "accelerating" if recent.rate > 0 else "steady"
    if recent.rate <= 0:
        return "reversing"
    ratio = recent.rate / prior.rate
    if ratio >= FASTER:
        return "accelerating"
    if ratio <= SLOWER:
        return "slowing"
    return "steady"


def compare(points: Sequence[Point], years: float, log: bool, as_of: float | None = None) -> dict:
    """Recent vs prior pace for a series, using only points up to ``as_of``."""
    pts = sorted(p for p in points if as_of is None or p[0] <= as_of)
    if not pts:
        return {"recent": None, "prior": None, "verdict": "too little data"}
    end = as_of if as_of is not None else pts[-1][0]
    recent = fit(pts, end - years, end, log)
    prior = fit(pts, end - 2 * years, end - years, log)
    return {"recent": recent, "prior": prior, "verdict": verdict(recent, prior)}


def project(p: Pace, target: float, log: bool) -> float | None:
    """When the recent fit reaches ``target``, as a decimal year (None if never)."""
    if p.rate <= 0:
        return None
    y = math.log2(target) if log else target
    return (y - p.intercept) / p.rate


def running_frontier(points: Iterable[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """The points that set a new record when they appeared."""
    best = -math.inf
    out = []
    for x, y, label in sorted(points, key=lambda p: (p[0], -p[1])):
        if y > best:
            out.append((x, y, label))
            best = y
    return out


def top_k_at_release(
    points: Iterable[tuple[float, float, str]], k: int = 10
) -> list[tuple[float, float, str]]:
    """Points that were among the ``k`` largest released so far (Epoch's frontier rule).

    A record-only rule leaves a handful of points per decade; "top 10 at
    release" keeps the frontier labs' near-record models too, which is how
    Epoch AI defines frontier models for its own trend fits.
    """
    seen: list[float] = []
    out = []
    for x, y, label in sorted(points, key=lambda p: p[0]):
        if sum(1 for v in seen if v > y) < k:
            out.append((x, y, label))
        seen.append(y)
    return out
