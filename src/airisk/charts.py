"""Self-contained SVG charts — no script, no CDN, identical bytes for identical data.

Colours come from CSS classes the page styles (``s1``…``s7``, ``fit``,
``proj``, ``ref``), so one chart serves light and dark themes.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from html import escape

W, H = 720, 280
PAD_L, PAD_R, PAD_T, PAD_B = 64, 16, 14, 30


def _nice_linear(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    # The last tick must reach ``hi``, or the tallest bar runs off the top.
    out, v = [], start
    while True:
        out.append(round(v, 10))
        if v >= hi - step * 1e-9:
            return out
        v += step


def _log_ticks(lo: float, hi: float) -> list[float]:
    a, b = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
    every = max(1, (b - a) // 7 + (1 if (b - a) > 7 else 0))
    ticks = [10.0**e for e in range(a, b + 1, every)]
    if b - a <= 2:
        ticks = sorted({t * m for t in ticks for m in (1, 2, 5)})
    return [t for t in ticks if lo / 1.0001 <= t <= hi * 1.0001] or [10.0**a]


class Frame:
    """Maps data to pixels for one chart."""

    def __init__(
        self, x0: float, x1: float, y0: float, y1: float, log: bool, w: int = W, h: int = H
    ):
        self.x0, self.x1, self.log, self.w, self.h = x0, x1, log, w, h
        if log:
            y0, y1 = max(y0, 1e-12), max(y1, y0 * 10)
            self.y0, self.y1 = 10 ** math.floor(math.log10(y0)), 10 ** math.ceil(math.log10(y1))
        else:
            t = _nice_linear(y0, y1)
            self.y0, self.y1 = t[0], t[-1]

    def x(self, v: float) -> float:
        return PAD_L + (v - self.x0) / (self.x1 - self.x0) * (self.w - PAD_L - PAD_R)

    def y(self, v: float) -> float:
        if self.log:
            v = max(v, self.y0)
            f = (math.log10(v) - math.log10(self.y0)) / (math.log10(self.y1) - math.log10(self.y0))
        else:
            f = (v - self.y0) / ((self.y1 - self.y0) or 1)
        return self.h - PAD_B - f * (self.h - PAD_T - PAD_B)

    def inside(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


def _axes(
    fr: Frame, yfmt: Callable[[float], str], y_ticks: Sequence[float] | None = None
) -> list[str]:
    out = []
    if y_ticks:
        yt = [t for t in y_ticks if fr.y0 <= t <= fr.y1]
    else:
        yt = _log_ticks(fr.y0, fr.y1) if fr.log else _nice_linear(fr.y0, fr.y1)
    for t in yt:
        y = fr.y(t)
        out.append(
            f'<line class="grid" x1="{PAD_L}" x2="{fr.w - PAD_R}" y1="{y:.1f}" y2="{y:.1f}"/>'
        )
        out.append(
            f'<text x="{PAD_L - 6}" y="{y + 3.5:.1f}" text-anchor="end">{escape(yfmt(t))}</text>'
        )
    span = fr.x1 - fr.x0
    step = next(s for s in (1, 2, 5, 10, 20, 25, 50) if span / s <= 9)
    first = math.ceil(fr.x0 / step) * step
    yr = first
    while yr <= fr.x1:
        x = fr.x(yr)
        out.append(
            f'<line class="axis" x1="{x:.1f}" x2="{x:.1f}" y1="{fr.h - PAD_B}" y2="{fr.h - PAD_B + 4}"/>'
        )
        out.append(
            f'<text x="{x:.1f}" y="{fr.h - PAD_B + 16}" text-anchor="middle">{int(yr)}</text>'
        )
        yr += step
    out.append(
        f'<line class="axis" x1="{PAD_L}" x2="{fr.w - PAD_R}" y1="{fr.h - PAD_B}" y2="{fr.h - PAD_B}"/>'
    )
    return out


def time_chart(
    series: Sequence[dict],
    log: bool,
    yfmt: Callable[[float], str],
    label: str,
    x_range: tuple[float, float] | None = None,
    fits: Sequence[dict] = (),
    refs: Sequence[tuple[float, str]] = (),
    marks: Sequence[tuple[float, str]] = (),
    h: int = H,
    y_min: float | None = None,
    y_ticks: Sequence[float] | None = None,
) -> str:
    """A dated chart.

    ``series``: ``{"points": [(x, y, label)], "kind": "dots"|"line"|"step", "cls": "s1",
    "fmt": callable}``. ``fits``: ``{"start", "end", "rate", "intercept", "cls", "dash"}``
    lines in the same space as the trend fit (log2 when ``log``). ``refs``: horizontal
    reference lines. ``marks``: vertical lines with a caption.
    """
    xs = [p[0] for s in series for p in s["points"]]
    ys = [p[1] for s in series for p in s["points"] if (p[1] > 0 or not log)]
    ys += [r[0] for r in refs]
    for f in fits:
        for x in (f["start"], f["end"]):
            v = f["intercept"] + f["rate"] * x
            ys.append(2**v if log else v)
            xs.append(x)
    if not xs or not ys:
        return ""
    x0, x1 = x_range or (math.floor(min(xs)), math.ceil(max(xs) + 0.01))
    lo = min(ys) if y_min is None else min(y_min, min(ys))
    fr = Frame(x0, x1, lo, max(ys), log, h=h)
    out = [f'<svg viewBox="0 0 {W} {h}" role="img" aria-label="{escape(label)}" class="chart">']
    out += _axes(fr, yfmt, y_ticks)
    for y, text in refs:
        if fr.y0 <= y <= fr.y1:
            py = fr.y(y)
            out.append(
                f'<line class="ref" x1="{PAD_L}" x2="{W - PAD_R}" y1="{py:.1f}" y2="{py:.1f}"/>'
            )
            out.append(
                f'<text class="reft" x="{W - PAD_R - 4}" y="{py - 4:.1f}" text-anchor="end">{escape(text)}</text>'
            )
    for x, text in marks:
        if x0 <= x <= x1:
            px = fr.x(x)
            out.append(
                f'<line class="ref" x1="{px:.1f}" x2="{px:.1f}" y1="{PAD_T}" y2="{h - PAD_B}"/>'
            )
            # Caption on whichever side has room, so it is never clipped.
            if px > W - 160:
                out.append(
                    f'<text class="reft" x="{px - 4:.1f}" y="{PAD_T + 10}" text-anchor="end">{escape(text)}</text>'
                )
            else:
                out.append(
                    f'<text class="reft" x="{px + 4:.1f}" y="{PAD_T + 10}">{escape(text)}</text>'
                )
    for f in fits:
        a, b = max(f["start"], x0), min(f["end"], x1)
        va, vb = f["intercept"] + f["rate"] * a, f["intercept"] + f["rate"] * b
        ya, yb = (2**va, 2**vb) if log else (va, vb)
        cls = f.get("cls", "fit") + (" dash" if f.get("dash") else "")
        out.append(
            f'<line class="{cls}" x1="{fr.x(a):.1f}" y1="{fr.y(ya):.1f}" x2="{fr.x(b):.1f}" y2="{fr.y(yb):.1f}"/>'
        )
    for s in series:
        pts = [p for p in s["points"] if x0 <= p[0] <= x1 and (p[1] > 0 or not log)]
        cls = s.get("cls", "s1")
        fmt = s.get("fmt", yfmt)
        if s.get("kind") in ("line", "step") and len(pts) > 1:
            coords = []
            for i, (x, y, _) in enumerate(pts):
                if s["kind"] == "step" and i:
                    coords.append(f"{fr.x(x):.1f},{fr.y(pts[i - 1][1]):.1f}")
                coords.append(f"{fr.x(x):.1f},{fr.y(y):.1f}")
            if s["kind"] == "step" and s.get("extend_to"):
                coords.append(f"{fr.x(min(s['extend_to'], x1)):.1f},{fr.y(pts[-1][1]):.1f}")
            out.append(f'<polyline class="{cls} ln" points="{" ".join(coords)}"/>')
        if s.get("kind") in ("dots", "line", "step") and s.get("dots", True):
            r = s.get("r", 2.6)
            for x, y, lab in pts:
                tip = f"{lab} — {fmt(y)}" if lab else fmt(y)
                out.append(
                    f'<circle class="{cls} dot" cx="{fr.x(x):.1f}" cy="{fr.y(y):.1f}" r="{r}"><title>{escape(tip)}</title></circle>'
                )
    out.append("</svg>")
    return "".join(out)


def stacked_bars(
    years: Sequence[int],
    cats: Sequence[str],
    data: dict[int, dict[str, int]],
    extra: dict[int, int],
    label: str,
    partial_year: int | None = None,
    h: int = 300,
) -> str:
    """Bars per year, stacked by category; ``extra`` is an unclassified top segment."""
    if not years:
        return ""
    totals = {y: sum(data.get(y, {}).values()) + extra.get(y, 0) for y in years}
    top = _nice_linear(0, max(totals.values()) or 1)[-1]
    n = len(years)
    plot_w = W - PAD_L - PAD_R
    bw = plot_w / n
    out = [f'<svg viewBox="0 0 {W} {h}" role="img" aria-label="{escape(label)}" class="chart">']
    for t in _nice_linear(0, top):
        y = h - PAD_B - t / top * (h - PAD_T - PAD_B)
        out.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text x="{PAD_L - 6}" y="{y + 3.5:.1f}" text-anchor="end">{int(t):,}</text>')
    for i, yr in enumerate(years):
        x = PAD_L + i * bw + bw * 0.12
        base = h - PAD_B
        segs = [(c, data.get(yr, {}).get(c, 0), f"s{j + 1}") for j, c in enumerate(cats)]
        segs.append(("Not yet classified", extra.get(yr, 0), "s0"))
        for c, v, cls in segs:
            if not v:
                continue
            hh = v / top * (h - PAD_T - PAD_B)
            base -= hh
            part = " part" if yr == partial_year else ""
            out.append(
                f'<rect class="{cls} bar{part}" x="{x:.1f}" y="{base:.1f}" width="{bw * 0.76:.1f}" height="{hh:.1f}"><title>{yr}: {escape(c)} {v:,}</title></rect>'
            )
        if n <= 20 or yr % 2 == 0:
            out.append(
                f'<text x="{x + bw * 0.38:.1f}" y="{h - PAD_B + 16}" text-anchor="middle">{"’" + str(yr)[2:] if n > 12 else yr}</text>'
            )
    out.append(
        f'<line class="axis" x1="{PAD_L}" x2="{W - PAD_R}" y1="{h - PAD_B}" y2="{h - PAD_B}"/>'
    )
    out.append("</svg>")
    return "".join(out)


def clock_face(seconds: int, label: str, size: int = 220) -> str:
    """The top of a clock face with the minute hand ``seconds`` before midnight."""
    c = size / 2
    r = c - 8
    out = [
        f'<svg viewBox="0 0 {size} {size}" role="img" aria-label="{escape(label)}" class="clock">'
    ]
    out.append(f'<circle class="face" cx="{c}" cy="{c}" r="{r}"/>')
    # The last 15 minutes before midnight, shaded.
    a0 = math.radians(-90 - 90)
    a1 = math.radians(-90)
    out.append(
        f'<path class="zone" d="M{c},{c} L{c + r * math.cos(a0):.1f},{c + r * math.sin(a0):.1f} '
        f'A{r},{r} 0 0 1 {c + r * math.cos(a1):.1f},{c + r * math.sin(a1):.1f} Z"/>'
    )
    for i in range(60):
        a = math.radians(i * 6 - 90)
        inner = r - (12 if i % 5 == 0 else 5)
        cls = "tick major" if i % 5 == 0 else "tick"
        out.append(
            f'<line class="{cls}" x1="{c + inner * math.cos(a):.1f}" y1="{c + inner * math.sin(a):.1f}" x2="{c + r * math.cos(a):.1f}" y2="{c + r * math.sin(a):.1f}"/>'
        )
    # Minute hand: 360 degrees per hour, so `seconds` before 12 is -seconds/10 degrees.
    a = math.radians(-90 - seconds / 10)
    out.append(
        f'<line class="hand" x1="{c}" y1="{c}" x2="{c + (r - 16) * math.cos(a):.1f}" y2="{c + (r - 16) * math.sin(a):.1f}"/>'
    )
    # Hour hand just before 12.
    ah = math.radians(-90 - seconds / 120)
    out.append(
        f'<line class="hand hour" x1="{c}" y1="{c}" x2="{c + (r * 0.55) * math.cos(ah):.1f}" y2="{c + (r * 0.55) * math.sin(ah):.1f}"/>'
    )
    out.append(f'<circle class="hub" cx="{c}" cy="{c}" r="4"/>')
    out.append("</svg>")
    return "".join(out)


def spark(points: Sequence[tuple[float, float]], log: bool, w: int = 120, h: int = 30) -> str:
    """A tiny trend line for the pace board."""
    pts = [(x, y) for x, y in points if y > 0 or not log]
    if len(pts) < 2:
        return ""
    xs = [p[0] for p in pts]
    ys = [math.log10(p[1]) if log else p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 == x0:
        return ""
    sy = (y1 - y0) or 1
    coords = " ".join(
        f"{2 + (x - x0) / (x1 - x0) * (w - 4):.1f},{h - 2 - (y - y0) / sy * (h - 4):.1f}"
        for x, y in zip(xs, ys)
    )
    return f'<svg viewBox="0 0 {w} {h}" class="spark" aria-hidden="true"><polyline points="{coords}"/></svg>'
