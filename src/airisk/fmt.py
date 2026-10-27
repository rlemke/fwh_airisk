"""Human-readable numbers for each unit the indicators use."""

from __future__ import annotations

import math

_SUP = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def sci(v: float) -> str:
    """2.1e25 -> '2.1×10²⁵'."""
    if v <= 0:
        return "0"
    e = int(math.floor(math.log10(v)))
    m = v / 10**e
    if round(m, 1) >= 10:
        m, e = m / 10, e + 1
    head = "" if abs(m - 1) < 0.05 else f"{m:.1f}×"
    return f"{head}10{str(e).translate(_SUP)}"


def money(v: float) -> str:
    for div, suf in ((1e12, " trillion"), (1e9, " billion"), (1e6, " million"), (1e3, "k")):
        if v >= div:
            x = v / div
            return f"${x:,.0f}{suf}" if x >= 100 else f"${x:.1f}{suf}".replace(".0 ", " ")
    return f"${v:,.0f}"


def duration(minutes: float) -> str:
    if minutes < 1:
        return f"{minutes * 60:.0f} s"
    if minutes < 60:
        return f"{minutes:.0f} min"
    h = minutes / 60
    if h < 10:
        whole = int(h)
        rest = round(minutes - whole * 60)
        return f"{whole} h {rest} min" if rest else f"{whole} h"
    if h < 100:
        return f"{h:.0f} h"
    return f"{h:,.0f} h"


def value(v: float, unit: str, scale: float = 1.0) -> str:
    x = v * scale
    if unit == "FLOP":
        return f"{sci(x)} FLOP"
    if unit.startswith("2023 US$") or unit.startswith("US$"):
        return money(x)
    if unit == "minutes":
        return duration(x)
    if unit.startswith("%"):
        return f"{x:.1f}%" if x < 10 else f"{x:.0f}%"
    if unit == "ECI points":
        return f"{x:.0f}"
    return f"{x:,.3g}"


def months(m: float | None) -> str:
    if m is None:
        return "—"
    if m >= 24:
        return f"{m / 12:.1f} years"
    return f"{m:.1f} months" if m < 10 else f"{m:.0f} months"


def factor_per_year(rate: float) -> str:
    """Doublings per year as a multiple per year (2 doublings -> 4×)."""
    f = 2**rate
    return f"{f:.1f}×" if f < 10 else f"{f:.0f}×"


def year_month(y: float) -> str:
    from .trend import date_of

    return date_of(y).strftime("%b %Y")
