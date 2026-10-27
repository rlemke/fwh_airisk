import json

import pytest

from airisk import indicators, sources
from airisk.site import build_site
from airisk.site.build import merge_history


def test_models_parse_and_pace(sources_dir):
    compute, cost = indicators.epoch_models(sources_dir["epoch_models"])
    assert len(compute.points) == 80 and len(cost.points) == 40
    pace = compute.pace()
    # The synthetic series doubles every 4 months after 2022 and every 6 before.
    assert pace["recent"].doubling_months == pytest.approx(4, rel=0.05)
    assert pace["verdict"] == "accelerating"


def test_benchmarks(sources_dir):
    b = indicators.epoch_benchmarks(sources_dir["epoch_benchmarks"])
    assert set(b) == {"eci", "metr", "cybench", "rli", "gpqa"}
    assert b["metr"].log and not b["cybench"].log
    assert b["metr"].latest[1] == pytest.approx(2**8.5)
    assert b["gpqa"].reference and b["metr"].milestones


def test_investment_is_world_only(sources_dir):
    inv = indicators.investment(sources_dir["owid_investment"])
    assert len(inv.points) == 13
    assert inv.pace()["recent"].rate == pytest.approx(__import__("math").log2(1.3), rel=1e-6)


def test_incidents(sources_dir):
    inc = indicators.incidents(sources_dir["aiid_snapshot"])
    assert inc.totals == {2022: 10, 2023: 20, 2024: 40, 2025: 60, 2026: 30}
    # Every fifth incident is unclassified.
    assert inc.unclassified[2025] == 12
    assert sum(inc.by_year[2025].values()) == 48
    assert inc.through.isoformat() == "2026-09-10"
    assert inc.ytd == (30, 60)
    assert inc.snapshot == "20261026"


def test_doomsday_clock(sources_dir):
    clock = indicators.doomsday_clock(sources_dir["doomsday_clock"])
    assert [(c.year, c.seconds) for c in clock] == [
        (1947, 420),
        (1991, 1020),
        (2020, 100),
        (2026, 85),
    ]
    assert [c.year for c in clock if c.mentions_ai] == [2020, 2026]
    assert "<ref>" not in clock[1].reason and "[[" not in clock[1].reason


def test_snapshot_choice_is_newest():
    html = (
        '<a href="https://example.org/backup-20261019101022.tar.bz2">'
        '<a href="https://example.org/backup-20261026101519.tar.bz2">'
        '<a href="https://example.org/backup-20250101000000.tar.bz2">'
    )
    url, stamp = sources.latest_incident_snapshot(html)
    assert stamp == "20261026101519" and url.endswith("backup-20261026101519.tar.bz2")
    plan = sources.plan(html)
    assert [p["key"] for p in plan][-1] == "aiid_snapshot"
    assert plan[-1]["dest"].endswith("aiid_snapshot.tar.bz2") and plan[-1]["stamp"] == stamp
    with pytest.raises(ValueError):
        sources.latest_incident_snapshot("<html></html>")


def test_surveys_have_citations():
    s = indicators.surveys()
    assert [r["year"] for r in s["rounds"]] == sorted(r["year"] for r in s["rounds"])
    assert all(r["citation"] and r["url"].startswith("https://") for r in s["rounds"])


def test_site_builds_deterministically(sources_dir, tmp_path):
    a = build_site(sources_dir, tmp_path / "a", history=[])
    b = build_site(sources_dir, tmp_path / "b", history=a["history"])
    assert a["paths"] == ["index.html", "paper.html", "data.html"]
    for p in a["paths"]:
        assert (tmp_path / "a" / p).read_bytes() == (tmp_path / "b" / p).read_bytes()
    assert len(b["history"]) == 1  # an unchanged reading is not appended twice
    index = (tmp_path / "a" / "index.html").read_text()
    paper = (tmp_path / "a" / "paper.html").read_text()
    assert "85 seconds" in index and "accelerating" in index
    assert "{{" not in paper and "None" not in paper.split("<article")[1].split("References")[0]
    json.dumps(a["summary"])  # the handler returns it through the step store


def test_history_merge():
    r1 = {"through": "2026-09-01", "indicators": {"x": {"verdict": "steady"}}}
    r2 = {"through": "2026-09-08", "indicators": {"x": {"verdict": "steady"}}}
    r3 = {"through": "2026-09-15", "indicators": {"x": {"verdict": "accelerating"}}}
    h = merge_history([], r1)
    h = merge_history(h, r2)
    assert [x["through"] for x in h] == ["2026-09-01"]
    h = merge_history(h, r3)
    assert [x["through"] for x in h] == ["2026-09-01", "2026-09-15"]
    assert merge_history(h, r3) == h
