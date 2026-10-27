"""Turn the fetched files into dated series, one per indicator.

Each indicator answers one question about one risk pathway, and carries its
own source, unit, scale and the window its pace is measured over. Parsing is
plain ``csv``/``zipfile``/``tarfile`` so the domain has no data-frame
dependency.
"""

from __future__ import annotations

import csv
import io
import json
import re
import tarfile
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import trend

csv.field_size_limit(1 << 26)  # Epoch and AIID carry multi-paragraph notes

Labeled = tuple[float, float, str]  # (decimal year, value, label)


@dataclass
class Indicator:
    key: str
    title: str
    question: str
    pathway: str
    unit: str
    source: str
    source_url: str
    log: bool  # exponential (doubling) or linear (points per year)
    years: float  # length of the recent and prior windows
    points: list[Labeled] = field(default_factory=list)  # everything, for the scatter
    fit_points: list[Labeled] = field(default_factory=list)  # what the pace is fitted on
    scale: float = 1.0  # displayed value = value * scale
    milestones: list[tuple[float, str]] = field(default_factory=list)
    reference: list[tuple[float, str]] = field(default_factory=list)  # horizontal lines
    note: str = ""

    @property
    def frontier(self) -> list[Labeled]:
        return trend.running_frontier(self.points)

    @property
    def latest(self) -> Labeled | None:
        f = self.frontier
        return f[-1] if f else None

    def pace(self, as_of: float | None = None) -> dict:
        return trend.compare([(x, y) for x, y, _ in self.fit_points], self.years, self.log, as_of)


def _f(v: str | None) -> float | None:
    try:
        x = float(v) if v not in (None, "") else None
    except ValueError:
        return None
    return x if x is not None and x == x else None  # drop NaN


def _date(v: str | None) -> float | None:
    if not v or not re.match(r"\d{4}-\d{2}-\d{2}", v):
        return None
    try:
        return trend.year_of(v[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------- Epoch models


def epoch_models(path: str | Path) -> tuple[Indicator, Indicator]:
    """Training compute and training cost of notable models since 2010."""
    flop, cost = [], []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            x = _date(r.get("Publication date"))
            if x is None or x < 2010:
                continue
            label = f"{r.get('Model', '').strip()} ({r.get('Organization', '').strip()})"
            c = _f(r.get("Training compute (FLOP)"))
            if c and c > 0:
                flop.append((x, c, label))
            usd = _f(r.get("Training compute cost (2023 USD)"))
            if usd and usd > 0:
                cost.append((x, usd, label))
    src = "Epoch AI, Notable AI Models"
    url = "https://epoch.ai/data/notable-ai-models"
    compute = Indicator(
        key="compute",
        title="Training compute of frontier models",
        question="How much computation goes into training the largest AI models?",
        pathway="capability",
        unit="FLOP",
        source=src,
        source_url=url,
        log=True,
        years=3,
        points=flop,
        fit_points=trend.top_k_at_release(flop, 10),
        milestones=[(1e27, "10²⁷ FLOP"), (1e28, "10²⁸ FLOP"), (1e29, "10²⁹ FLOP")],
        note="Pace is fitted on models that were among the ten most compute-intensive when they were published, which is how Epoch AI defines the frontier.",
    )
    price = Indicator(
        key="cost",
        title="Cost of a frontier training run",
        question="How much does one frontier training run cost?",
        pathway="race",
        unit="2023 US$",
        source=src,
        source_url=url,
        log=True,
        years=3,
        points=cost,
        fit_points=trend.top_k_at_release(cost, 10),
        milestones=[(1e9, "$1 billion"), (1e10, "$10 billion")],
        note="Hardware and energy cost of the final training run only, in 2023 dollars; research, staff and failed runs are excluded.",
    )
    return compute, price


# ------------------------------------------------------------ Epoch benchmarks

_BENCH = {
    # key: (file, value column, title, question, pathway, log, years, scale, unit, note)
    "eci": (
        "epoch_capabilities_index/eci_scores.csv",
        "eci",
        "date",
        "General capability (Epoch Capabilities Index)",
        "How capable is the best AI model across dozens of benchmarks?",
        "capability",
        False,
        2,
        1.0,
        "ECI points",
        "Epoch's index stitches many benchmarks onto one scale, so progress can be followed after any single test is saturated.",
    ),
    "metr": (
        "metr_time_horizons_external.csv",
        "Time horizon",
        "Release date",
        "Autonomy: length of task an AI agent can finish",
        "How long a task (measured in skilled-human time) can an AI agent complete on its own, half the time?",
        "control",
        True,
        2,
        1.0,
        "minutes",
        "METR's 50% time horizon on software and research tasks. The longer the tasks an agent completes unattended, the less a human is in the loop. METR measured few models released before 2024, so the earlier window rests on a handful of GPT-4 versions.",
    ),
    "cybench": (
        "cybench_external.csv",
        "Unguided % Solved",
        "Release date",
        "Offensive cyber skill (Cybench)",
        "What share of professional capture-the-flag hacking challenges can an AI solve with no hints?",
        "cyber",
        False,
        1,
        100.0,
        "% solved",
        "Forty capture-the-flag tasks from professional competitions. A bounded score, so its pace is in percentage points per year.",
    ),
    "rli": (
        "rli_external.csv",
        "Score",
        "Release date",
        "Paid work an AI can do (Remote Labor Index)",
        "What share of real freelance projects does an AI agent deliver at a quality a client would accept?",
        "economic",
        True,
        1,
        100.0,
        "% of projects",
        "Real projects from freelance platforms, judged against the human deliverable. Still far from its ceiling, so it is fitted as growth.",
    ),
    "gpqa": (
        "gpqa_diamond.csv",
        "mean_score",
        "Release date",
        "Expert science knowledge (GPQA Diamond)",
        "How well does AI answer graduate-level biology, chemistry and physics questions written to defeat web search?",
        "bio",
        False,
        2,
        100.0,
        "% correct",
        "A proxy only: knowing the science is not the same as giving useful help with a weapon, and no open benchmark measures that uplift over time.",
    ),
}


def epoch_benchmarks(zip_path: str | Path) -> dict[str, Indicator]:
    out: dict[str, Indicator] = {}
    with zipfile.ZipFile(zip_path) as z:
        names = {Path(n).as_posix(): n for n in z.namelist()}
        for key, (
            fname,
            col,
            dcol,
            title,
            q,
            pathway,
            log,
            years,
            scale,
            unit,
            note,
        ) in _BENCH.items():
            member = next((n for p, n in names.items() if p.endswith(fname)), None)
            if member is None:
                continue
            pts = []
            with z.open(member) as fh:
                for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8")):
                    x, y = _date(r.get(dcol)), _f(r.get(col))
                    if x is None or y is None or (log and y <= 0):
                        continue
                    label = (
                        r.get("Display name")
                        or r.get("Name")
                        or r.get("Model version")
                        or r.get("Model")
                        or ""
                    ).strip()
                    pts.append((x, y, label))
            ind = Indicator(
                key=key,
                title=title,
                question=q,
                pathway=pathway,
                unit=unit,
                source="Epoch AI, Benchmarking Hub" + (" (METR data)" if key == "metr" else ""),
                source_url="https://epoch.ai/benchmarks",
                log=log,
                years=years,
                points=pts,
                scale=scale,
                note=note,
            )
            ind.fit_points = ind.frontier
            out[key] = ind
    if "metr" in out:
        out["metr"].milestones = [
            (480, "a work day (8 h)"),
            (2400, "a work week (40 h)"),
            (10020, "a work month (167 h)"),
            (120000, "a work year (2,000 h)"),
        ]
    if "gpqa" in out:
        # Rein et al. (2023): PhD-level domain experts scored about 65%, and
        # skilled non-experts with unrestricted web access about 34%.
        out["gpqa"].reference = [(0.65, "domain experts ≈65%"), (0.34, "non-experts with web ≈34%")]
    if "cybench" in out:
        out["cybench"].reference = []
    return out


# ------------------------------------------------------------- investment


def investment(path: str | Path) -> Indicator:
    pts = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("entity") != "World":
                continue
            yr, v = _f(r.get("year")), _f(r.get("private_investment"))
            if yr and v:
                pts.append((yr + 0.5, v, str(int(yr))))
    return Indicator(
        key="investment",
        title="Private investment in AI",
        question="How much private money flows into AI companies each year?",
        pathway="race",
        unit="US$ per year",
        source="Our World in Data, from Quid via the Stanford AI Index",
        source_url="https://ourworldindata.org/grapher/private-investment-in-artificial-intelligence",
        log=True,
        years=3,
        points=pts,
        fit_points=pts,
        note="Private investment only (venture and private equity), world total, in constant US dollars; public markets and government spending are excluded.",
    )


# ------------------------------------------------------------- incidents

MIT_DOMAINS = {
    "1": "Discrimination & toxicity",
    "2": "Privacy & security",
    "3": "Misinformation",
    "4": "Malicious use",
    "5": "Human–computer interaction",
    "6": "Socioeconomic & environmental",
    "7": "AI system safety & failures",
}


@dataclass
class Incidents:
    by_year: dict[int, Counter]  # year -> MIT domain -> incidents
    totals: dict[int, int]
    unclassified: dict[int, int]
    through: date | None
    ytd: tuple[int, int] | None  # (this year to date, same span last year)
    snapshot: str

    @property
    def years(self) -> list[int]:
        return sorted(self.totals)


def incidents(tar_path: str | Path, first_year: int = 2010, stamp: str = "") -> Incidents:
    """Incidents per year by MIT risk domain, read straight from the snapshot."""
    want = {"incidents.csv": None, "classifications_MIT.csv": None}
    with tarfile.open(tar_path, mode="r|bz2") as tf:
        for m in tf:
            base = Path(m.name).name
            if base in want and m.isfile() and want[base] is None:
                fh = tf.extractfile(m)
                if fh is not None:
                    want[base] = fh.read().decode("utf-8", "replace")
            if all(v is not None for v in want.values()):
                break
    if want["incidents.csv"] is None:
        raise ValueError(f"{tar_path}: no incidents.csv in the snapshot")
    domain: dict[int, str] = {}
    for r in csv.DictReader(io.StringIO(want["classifications_MIT.csv"] or "")):
        iid = r.get("Incident ID")
        d = (r.get("Risk Domain") or "").split(".", 1)[0].strip()
        if iid and iid.isdigit() and d in MIT_DOMAINS:
            domain[int(iid)] = MIT_DOMAINS[d]
    dates: list[tuple[date, int]] = []
    for r in csv.DictReader(io.StringIO(want["incidents.csv"])):
        iid, d = r.get("incident_id"), (r.get("date") or "")[:10]
        if not (iid and iid.isdigit() and re.match(r"\d{4}-\d{2}-\d{2}$", d)):
            continue
        dates.append((date.fromisoformat(d), int(iid)))
    by_year: dict[int, Counter] = defaultdict(Counter)
    totals: Counter = Counter()
    unclassified: Counter = Counter()
    for d, iid in dates:
        if d.year < first_year:
            continue
        totals[d.year] += 1
        if iid in domain:
            by_year[d.year][domain[iid]] += 1
        else:
            unclassified[d.year] += 1
    through = max((d for d, _ in dates), default=None)
    ytd = None
    if through:
        cut_prev = (
            through.replace(year=through.year - 1)
            if not (through.month == 2 and through.day == 29)
            else date(through.year - 1, 2, 28)
        )
        ytd = (
            sum(1 for d, _ in dates if d.year == through.year and d <= through),
            sum(1 for d, _ in dates if d.year == through.year - 1 and d <= cut_prev),
        )
    found = re.search(r"(\d{8})", stamp or Path(tar_path).name)
    return Incidents(
        by_year=dict(by_year),
        totals=dict(totals),
        unclassified=dict(unclassified),
        through=through,
        ytd=ytd,
        snapshot=found.group(1) if found else "",
    )


# -------------------------------------------------------- Doomsday Clock


@dataclass
class ClockSetting:
    year: int
    seconds: int  # to midnight
    reason: str
    mentions_ai: bool


_AI_WORDS = re.compile(
    r"artificial intelligence|\bAI\b|disruptive technolog|advancing technolog|emerging technolog",
    re.I,
)


def _plain(wiki: str) -> str:
    s = re.sub(r"<ref[^>]*/>", "", wiki)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    return re.sub(r"\s+", " ", s).strip()


def doomsday_clock(path: str | Path) -> list[ClockSetting]:
    """Every setting of the clock, from its time column (23:58:35 = 85 s)."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    out: list[ClockSetting] = []
    year = None
    seconds = None
    for line in lines:
        m = re.match(r"^\|\s*(\d{4})\s*$", line)
        if m:
            year, seconds = int(m.group(1)), None
            continue
        m = re.match(r"^\|\s*23:(\d{2})(?::(\d{2}))?\s*$", line)
        if m and year is not None:
            seconds = 3600 - (int(m.group(1)) * 60 + int(m.group(2) or 0))
            continue
        if year is not None and seconds is not None and line.startswith('| align="left" |'):
            reason = _plain(line.split("|", 2)[2])
            out.append(ClockSetting(year, seconds, reason, bool(_AI_WORDS.search(reason))))
            year, seconds = None, None
    if not out:
        raise ValueError(f"{path}: no Doomsday Clock settings found")
    return sorted(out, key=lambda c: c.year)


# ---------------------------------------------------------------- surveys


def surveys() -> dict:
    return json.loads((Path(__file__).parent / "data" / "surveys.json").read_text(encoding="utf-8"))
