"""The files the indicators are computed from, and where each one comes from.

Every source is open and needs no key:

- **Epoch AI** — its database of notable AI models (training compute and
  cost, by publication date) and its benchmarking hub (the Epoch
  Capabilities Index, METR's task time horizons, Cybench, the Remote Labor
  Index, GPQA Diamond). CC BY.
- **Our World in Data** — private investment in AI (from Quid via the
  Stanford AI Index).
- **AI Incident Database** — a weekly full snapshot; each incident carries the
  MIT AI Risk Repository domain it falls under.
- **Wikipedia** — the Doomsday Clock's setting by year, with the Bulletin of
  the Atomic Scientists' stated reasons.

Expert-survey results are a handful of published numbers, so they ship with
the package (``data/surveys.json``) with a citation for each.
"""

from __future__ import annotations

import re
import urllib.request

from .storage import raw_path

EPOCH = "https://epoch.ai/data"
OWID = "https://ourworldindata.org/grapher"
AIID_SNAPSHOTS = "https://incidentdatabase.ai/research/snapshots/"
WIKI_CLOCK = "https://en.wikipedia.org/w/index.php?title=Doomsday_Clock&action=raw"
USER_AGENT = "facetwork-airisk/0.1 (+https://github.com/rlemke/fwh_airisk)"

# key -> (url, stored file name, max age in hours). 0 = ask upstream every
# run (a conditional GET; an unchanged file is not downloaded again).
STATIC = {
    "epoch_models": (f"{EPOCH}/notable_ai_models.csv", "notable_ai_models.csv", 0),
    "epoch_benchmarks": (f"{EPOCH}/benchmark_data.zip", "benchmark_data.zip", 0),
    "owid_investment": (
        f"{OWID}/private-investment-in-artificial-intelligence.csv"
        "?v=1&csvType=full&useColumnShortNames=true",
        "private_investment_ai.csv",
        24,
    ),
    "doomsday_clock": (WIKI_CLOCK, "doomsday_clock.wiki", 0),
}

_SNAPSHOT = re.compile(r"https://[A-Za-z0-9.-]+/backup-(\d{14})\.tar\.bz2")


def latest_incident_snapshot(html: str) -> tuple[str, str]:
    """The newest snapshot URL on the AIID snapshots page, and its stamp.

    Snapshot names carry their creation time, so the newest is the largest
    stamp — not whichever happens to be listed first.
    """
    found = {m.group(1): m.group(0) for m in _SNAPSHOT.finditer(html)}
    if not found:
        raise ValueError("no snapshot link on the AI Incident Database snapshots page")
    stamp = max(found)
    return found[stamp], stamp


def _get(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
        return resp.read().decode("utf-8", "replace")


def plan(snapshots_html: str | None = None) -> list[dict]:
    """Every file to fetch, as ``{key, url, dest, max_age_hours}``.

    The incident snapshot is resolved here because its URL changes weekly.
    It is stored under ONE name and asked for every run: the same snapshot
    answers 304, a new week's replaces it, so old 120 MB snapshots never pile
    up. Its date travels in the URL, which Build reads.
    """
    out = [
        {"key": k, "url": url, "dest": raw_path(name), "max_age_hours": float(age)}
        for k, (url, name, age) in STATIC.items()
    ]
    html = snapshots_html if snapshots_html is not None else _get(AIID_SNAPSHOTS)
    url, stamp = latest_incident_snapshot(html)
    out.append(
        {
            "key": "aiid_snapshot",
            "url": url,
            "dest": raw_path("aiid_snapshot.tar.bz2"),
            "max_age_hours": 0.0,
            "stamp": stamp,
        }
    )
    return out
