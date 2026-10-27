import pytest

from airisk import charts, fmt, trend


def _exp(start: float, end: float, months: float, step: float = 0.1):
    out, x = [], start
    while x <= end + 1e-9:
        out.append((round(x, 4), 2 ** ((x - start) * 12 / months)))
        x += step
    return out


def test_fit_recovers_doubling_time():
    p = trend.fit(_exp(2020, 2024, 6), 2020, 2024, log=True)
    assert p.doubling_months == pytest.approx(6, rel=1e-6)


def _bend(months_before: float, months_after: float):
    """Doubling every ``months_before`` 2018-2022, then every ``months_after``."""
    level = 2 ** ((2022 - 2018) * 12 / months_before)
    return _exp(2018, 2022, months_before) + [
        (x, level * 2 ** ((x - 2022) * 12 / months_after)) for x, _ in _exp(2022.1, 2024, 1)
    ]


def test_compare_flags_acceleration_and_slowdown():
    assert trend.compare(_bend(8, 4), 2, log=True)["verdict"] == "accelerating"
    assert trend.compare(_bend(4, 8), 2, log=True)["verdict"] == "slowing"
    assert trend.compare(_bend(6, 6), 2, log=True)["verdict"] == "steady"


def test_compare_needs_three_points_per_window():
    out = trend.compare([(2020, 1.0), (2023, 2.0), (2024, 4.0)], 2, log=True)
    assert out["verdict"] == "too little data"


def test_as_of_ignores_later_points():
    pts = _exp(2016, 2024, 6)
    early = trend.compare(pts + [(2025, 1e30)], 2, log=True, as_of=2024)
    assert early["recent"].doubling_months == pytest.approx(6, rel=1e-6)


def test_projection_hits_target():
    p = trend.fit(_exp(2020, 2024, 12), 2020, 2024, log=True)
    assert trend.project(p, 2**10, log=True) == pytest.approx(2030, abs=1e-6)


def test_frontier_rules():
    pts = [(2020.0, 5.0, "a"), (2020.5, 3.0, "b"), (2021.0, 6.0, "c"), (2021.5, 6.0, "d")]
    assert [p[2] for p in trend.running_frontier(pts)] == ["a", "c"]
    assert [p[2] for p in trend.top_k_at_release(pts, 1)] == ["a", "c", "d"]


def test_decimal_year_round_trip():
    for d in ("2024-02-29", "2025-12-31", "2026-01-01"):
        assert trend.date_of(trend.year_of(d)).isoformat() == d


def test_linear_ticks_reach_the_maximum():
    # 463 once produced ticks ending at 400, so the tallest bar ran off the chart.
    assert charts._nice_linear(0, 463)[-1] >= 463


def test_formats():
    assert fmt.sci(2.1e25) == "2.1×10²⁵"
    assert fmt.sci(1e27) == "10²⁷"
    assert fmt.money(2.9e11) == "$290 billion"
    assert fmt.duration(1044.8) == "17 h"
    assert fmt.duration(90) == "1 h 30 min"
    assert fmt.months(5.3) == "5.3 months"
