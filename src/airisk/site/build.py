"""Render the site from the fetched files.

Three pages:

- ``index.html`` — the pace board: every indicator's latest value, its pace
  now and two years ago, and whether it is speeding up; beside it the
  Bulletin of the Atomic Scientists' Doomsday Clock.
- ``paper.html`` — the paper. Its numbers are filled in from the data at
  build time, so the text moves when the indicators do.
- ``data.html`` — every indicator in full: all points, the frontier, the
  fitted paces, how the pace itself has changed, sources and method, and the
  readings recorded at each refresh.

Output depends only on the data (no build clock), so an unchanged week
re-renders byte-identical pages and the publisher commits nothing.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .. import charts, fmt, indicators, trend
from ..indicators import Indicator

PATHWAYS = {
    "capability": (
        "Raw capability",
        "How powerful the systems are — the engine under every other pathway.",
    ),
    "control": ("Loss of control", "AI acting on its own for longer, with less human oversight."),
    "cyber": (
        "Misuse: cyberattacks",
        "AI used to find and exploit weaknesses in computer systems.",
    ),
    "bio": (
        "Misuse: biological and chemical weapons",
        "AI lowering the expertise needed to cause mass casualties.",
    ),
    "economic": (
        "Economic disempowerment",
        "Human work, and the leverage it gives people, being displaced.",
    ),
    "race": ("Race dynamics", "Competitive pressure to build faster than safety can keep up."),
}

BOARD_ORDER = ["compute", "eci", "metr", "cybench", "gpqa", "rli", "investment", "cost"]
PACE_FROM = 2016.0
PACE_STEP = 0.25  # quarterly as-of readings for the pace-over-time charts
# Duration axes read in units people use, not powers of ten of minutes.
DURATION_TICKS = [1 / 60, 10 / 60, 1, 10, 60, 480, 2400, 10020, 120000, 1200000]


def load_all(paths: dict[str, str], stamps: dict[str, str] | None = None) -> dict:
    """Parse every fetched file. ``paths`` maps a source key to a LOCAL path;
    ``stamps`` carries a source's date when its file name does not."""
    compute, cost = indicators.epoch_models(paths["epoch_models"])
    inds: dict[str, Indicator] = {"compute": compute, "cost": cost}
    inds.update(indicators.epoch_benchmarks(paths["epoch_benchmarks"]))
    inds["investment"] = indicators.investment(paths["owid_investment"])
    return {
        "indicators": inds,
        "incidents": indicators.incidents(
            paths["aiid_snapshot"], stamp=(stamps or {}).get("aiid_snapshot", "")
        ),
        "clock": indicators.doomsday_clock(paths["doomsday_clock"]),
        "surveys": indicators.surveys(),
    }


def _yfmt(ind: Indicator) -> Callable[[float], str]:
    if ind.unit == "FLOP":
        return fmt.sci
    if "US$" in ind.unit:
        return fmt.money
    if ind.unit == "minutes":
        return fmt.duration
    if ind.unit.startswith("%"):
        return lambda v: f"{v * ind.scale:g}%"
    return lambda v: f"{v:g}"


def _pace_text(p: trend.Pace | None, ind: Indicator) -> str:
    if p is None:
        return "—"
    if ind.log:
        if p.rate <= 0:
            return "not growing"
        return (
            f"doubling every {fmt.months(p.doubling_months)}, {fmt.factor_per_year(p.rate)} a year"
        )
    per = p.rate * ind.scale
    unit = "points" if ind.unit.startswith("%") else ind.unit
    return f"{per:+.1f} {unit} a year"


def _pace_history(ind: Indicator, end: float) -> list[tuple[float, float, str]]:
    """The recent-window pace as it would have been measured at each quarter."""
    out = []
    t = max(
        PACE_FROM, math.ceil(min((x for x, _, _ in ind.fit_points), default=end) + 2 * ind.years)
    )
    while t <= end + 1e-9:
        p = ind.pace(as_of=t)["recent"]
        if p is not None:
            v = p.doubling_months if ind.log else p.rate * ind.scale
            if v is not None and v > 0:
                out.append((t, v, fmt.year_month(t)))
        t = round(t + PACE_STEP, 4)
    return out


def _indicator_view(ind: Indicator, through: float) -> dict:
    pace = ind.pace()
    recent, prior = pace["recent"], pace["prior"]
    latest = ind.latest
    yfmt = _yfmt(ind)
    vfmt = lambda v: fmt.value(v, ind.unit, ind.scale)  # noqa: E731
    first = max(2010.0, math.floor(min((x for x, _, _ in ind.points), default=2010)))
    proj_end = through + 2
    fits = []
    if prior:
        fits.append(
            {
                "start": prior.start,
                "end": prior.end,
                "rate": prior.rate,
                "intercept": prior.intercept,
                "cls": "fit prior",
            }
        )
    if recent:
        fits.append(
            {
                "start": recent.start,
                "end": recent.end,
                "rate": recent.rate,
                "intercept": recent.intercept,
                "cls": "fit",
            }
        )
        # A share cannot pass 100%, so a growth line is never extended for one.
        if ind.log and recent.rate > 0 and not ind.unit.startswith("%"):
            fits.append(
                {
                    "start": recent.end,
                    "end": proj_end,
                    "rate": recent.rate,
                    "intercept": recent.intercept,
                    "cls": "proj",
                    "dash": True,
                }
            )
    refs = list(ind.reference)  # in the data's own scale, like the points
    chart = charts.time_chart(
        [
            {"points": ind.points, "kind": "dots", "cls": "s0", "r": 2.0, "fmt": vfmt},
            {
                "points": ind.frontier,
                "kind": "step",
                "cls": "s1",
                "fmt": vfmt,
                "extend_to": through,
            },
        ],
        log=ind.log,
        yfmt=yfmt,
        label=f"{ind.title} over time",
        x_range=(
            first,
            proj_end if any(f.get("dash") for f in fits) else math.ceil(through + 0.01),
        ),
        fits=fits,
        refs=refs,
        y_min=None if ind.log or ind.unit == "ECI points" else 0,
        y_ticks=DURATION_TICKS if ind.unit == "minutes" else None,
    )
    hist = _pace_history(ind, through)
    pace_chart = ""
    if len(hist) >= 2:
        pace_chart = charts.time_chart(
            [
                {
                    "points": hist,
                    "kind": "line",
                    "cls": "s2",
                    "r": 1.6,
                    "fmt": (lambda v: fmt.months(v)) if ind.log else (lambda v: f"{v:+.1f} a year"),
                }
            ],
            log=False,
            yfmt=(lambda v: f"{v:g} mo") if ind.log else (lambda v: f"{v:g}"),
            label=f"Pace of {ind.title} over time",
            h=190,
        )
    milestones = []
    if ind.log and recent and recent.rate > 0 and latest:
        for target, text in ind.milestones:
            if target > latest[1]:
                when = trend.project(recent, target, True)
                if when is not None and when < through + 25:
                    # A date already past means the trend line has crossed the
                    # target but no measured model has yet: the data lags, or
                    # the trend has bent. Reported as such, never hidden.
                    milestones.append(
                        {
                            "label": text,
                            "when": fmt.year_month(when),
                            "years": when - through,
                            "overdue": when < through,
                        }
                    )
    return {
        "key": ind.key,
        "title": ind.title,
        "question": ind.question,
        "pathway": ind.pathway,
        "pathway_name": PATHWAYS[ind.pathway][0],
        "unit": ind.unit,
        "source": ind.source,
        "source_url": ind.source_url,
        "note": ind.note,
        "log": ind.log,
        "years": ind.years,
        "n_points": len(ind.points),
        "n_fit": len(ind.fit_points),
        "latest_value": vfmt(latest[1]) if latest else "—",
        "latest_label": latest[2] if latest else "",
        "latest_date": fmt.year_month(latest[0]) if latest else "",
        "latest_raw": latest[1] if latest else None,
        "recent": _pace_text(recent, ind),
        "prior": _pace_text(prior, ind),
        "recent_rate": recent.rate if recent else None,
        "prior_rate": prior.rate if prior else None,
        "recent_months": recent.doubling_months if (recent and ind.log) else None,
        "prior_months": prior.doubling_months if (prior and ind.log) else None,
        "recent_n": recent.n if recent else 0,
        "verdict": pace["verdict"],
        "chart": Markup(chart),
        "pace_chart": Markup(pace_chart),
        "spark": Markup(
            charts.spark([(x, y) for x, y, _ in ind.frontier if x >= through - 6], ind.log)
        ),
        "milestones": milestones,
    }


def _clock_view(settings: list[indicators.ClockSetting], through: float) -> dict:
    pts = [
        (s.year + 0.08, s.seconds / 60.0, f"{s.year}: {_clock_text(s.seconds)}") for s in settings
    ]
    ai_years = [s.year for s in settings if s.mentions_ai]
    chart = charts.time_chart(
        [
            {
                "points": pts,
                "kind": "step",
                "cls": "s3",
                "extend_to": through,
                "fmt": lambda v: _clock_text(round(v * 60)),
            }
        ],
        log=False,
        yfmt=lambda v: f"{v:g} min",
        label="Doomsday Clock, minutes to midnight, 1947 to now",
        x_range=(1945, math.ceil(through + 0.01)),
        marks=[(y + 0.08, "technology cited") for y in ai_years[:1]],
        h=230,
        y_min=0,
    )
    cur = settings[-1]
    closest_before = min((s for s in settings[:-1]), key=lambda s: s.seconds, default=None)
    return {
        "chart": Markup(chart),
        "face": Markup(
            charts.clock_face(
                cur.seconds, f"Doomsday Clock: {_clock_text(cur.seconds)} to midnight"
            )
        ),
        "current": _clock_text(cur.seconds),
        "current_seconds": cur.seconds,
        "year": cur.year,
        "reason": cur.reason,
        "settings": [
            {
                "year": s.year,
                "text": _clock_text(s.seconds),
                "reason": s.reason,
                "ai": s.mentions_ai,
            }
            for s in reversed(settings)
        ],
        "ai_years": ai_years,
        "first": settings[0],
        "farthest": max(settings, key=lambda s: s.seconds),
        "closest_before": closest_before,
        "farthest_text": _clock_text(max(s.seconds for s in settings)),
    }


def _clock_text(seconds: int) -> str:
    if seconds < 120 or seconds % 60:
        return f"{seconds} seconds"
    return f"{seconds // 60} minutes"


def _incident_view(inc: indicators.Incidents) -> dict:
    years = [y for y in inc.years if y >= 2014]
    cats = list(indicators.MIT_DOMAINS.values())
    partial = inc.through.year if inc.through else None
    chart = charts.stacked_bars(
        years,
        cats,
        {y: dict(inc.by_year.get(y, {})) for y in years},
        inc.unclassified,
        label="Reported AI incidents per year by risk domain",
        partial_year=partial,
    )
    last_full = max((y for y in years if y != partial), default=None)
    totals = {y: inc.totals.get(y, 0) for y in years}
    domain_share = []
    if last_full:
        tot = sum(inc.by_year.get(last_full, {}).values()) or 1
        for c in cats:
            v = inc.by_year.get(last_full, {}).get(c, 0)
            domain_share.append({"domain": c, "count": v, "share": v / tot})
        domain_share.sort(key=lambda d: -d["count"])
    growth = None
    if last_full and totals.get(last_full - 3):
        growth = (totals[last_full] / totals[last_full - 3]) ** (1 / 3) - 1
    return {
        "chart": Markup(chart),
        "cats": [(f"s{i + 1}", c) for i, c in enumerate(cats)],
        "totals": totals,
        "last_full": last_full,
        "last_full_total": totals.get(last_full, 0) if last_full else 0,
        "partial": partial,
        "through": inc.through.isoformat() if inc.through else "",
        "ytd": inc.ytd,
        "domain_share": domain_share,
        "growth3": growth,
        "all_time": sum(inc.totals.values()),
        "snapshot": inc.snapshot,
    }


def _survey_view(s: dict) -> dict:
    rounds = s["rounds"]
    med = [
        (r["year"] + 0.5, r["extremely_bad_median"], f"{r['year']} median")
        for r in rounds
        if r.get("extremely_bad_median") is not None
    ]
    mean = [
        (r["year"] + 0.5, r["extremely_bad_mean"], f"{r['year']} mean")
        for r in rounds
        if r.get("extremely_bad_mean") is not None
    ]
    pct = lambda v: f"{v * 100:.0f}%"  # noqa: E731
    p_chart = charts.time_chart(
        [
            {"points": med, "kind": "line", "cls": "s1", "fmt": pct},
            {"points": mean, "kind": "line", "cls": "s2", "fmt": pct},
        ],
        log=False,
        yfmt=pct,
        label="AI researchers' probability of an extremely bad outcome",
        x_range=(2015, rounds[-1]["year"] + 2),
        h=200,
        y_min=0,
    )
    hl = [
        (r["year"] + 0.5, r["hlmi_50_year"], f"surveyed {r['year']}: 50% by {r['hlmi_50_year']}")
        for r in rounds
        if r.get("hlmi_50_year")
    ]
    h_chart = charts.time_chart(
        [{"points": hl, "kind": "line", "cls": "s3", "fmt": lambda v: f"{v:.0f}"}],
        log=False,
        yfmt=lambda v: f"{v:.0f}",
        label="Year by which AI researchers give even odds of human-level AI",
        x_range=(2015, rounds[-1]["year"] + 2),
        h=200,
    )
    return {
        "rounds": rounds,
        "about": s["_about"],
        "p_chart": Markup(p_chart),
        "h_chart": Markup(h_chart),
        "latest": rounds[-1],
    }


def summarize(views: dict[str, dict], through: str) -> dict:
    """The compact reading recorded at each refresh."""
    return {
        "through": through,
        "indicators": {
            k: {
                "latest": v["latest_raw"],
                "latest_text": v["latest_value"],
                "pace": v["recent"],
                "recent_rate": None if v["recent_rate"] is None else round(v["recent_rate"], 4),
                "verdict": v["verdict"],
            }
            for k, v in views.items()
        },
    }


def merge_history(history: list[dict], reading: dict) -> list[dict]:
    """Append a reading unless it repeats the last one; same data date replaces."""
    out = [h for h in history if h.get("through") != reading["through"]]
    if out and out[-1].get("indicators") == reading["indicators"]:
        return out
    out.append(reading)
    return sorted(out, key=lambda h: h["through"])


def build_site(
    paths: dict[str, str],
    out_dir: str | Path,
    history: list[dict] | None = None,
    log=None,
    stamps: dict[str, str] | None = None,
) -> dict:
    data = load_all(paths, stamps)
    inds: dict[str, Indicator] = data["indicators"]
    latest_dates = [i.latest[0] for i in inds.values() if i.latest]
    through = max(latest_dates)
    views = {k: _indicator_view(inds[k], through) for k in BOARD_ORDER if k in inds}
    through_str = trend.date_of(through).isoformat()
    reading = summarize(views, through_str)
    history = merge_history(list(history or []), reading)
    accel = [v for v in views.values() if v["verdict"] == "accelerating"]
    slow = [v for v in views.values() if v["verdict"] in ("slowing", "reversing")]
    ctx = {
        "views": views,
        "board": list(views.values()),
        "pathways": PATHWAYS,
        "by_pathway": {p: [v for v in views.values() if v["pathway"] == p] for p in PATHWAYS},
        "clock": _clock_view(data["clock"], through),
        "incidents": _incident_view(data["incidents"]),
        "surveys": _survey_view(data["surveys"]),
        "through": through_str,
        "through_label": trend.date_of(through).strftime("%-d %B %Y"),
        "accelerating": accel,
        "slowing": slow,
        "history": list(reversed(history)),
        "history_n": len(history),
        "fmt": fmt,
        "trend_cfg": {"faster": trend.FASTER, "slower": trend.SLOWER},
    }
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for page in ("index.html", "paper.html", "data.html"):
        html = env.get_template(page).render(page=page, **ctx)
        (out / page).write_text(html, encoding="utf-8")
        written.append(page)
        if log:
            log(f"rendered {page} ({len(html):,} bytes)", level="info")
    size = sum((out / p).stat().st_size for p in written)
    return {
        "paths": written,
        "files": len(written),
        "bytes": size,
        "through": through_str,
        "history": history,
        "summary": {
            k: {"latest": v["latest_value"], "pace": v["recent"], "verdict": v["verdict"]}
            for k, v in views.items()
        },
        "accelerating": [v["key"] for v in accel],
    }
