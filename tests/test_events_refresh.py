"""The weekly events search: what passes the checks, and the search loop itself."""

from __future__ import annotations

from types import SimpleNamespace as NS

from airisk import events_refresh as er
from airisk import indicators

TODAY = "2026-11-30"
OK = "https://news.example.org/story"


def _base() -> dict:
    return indicators.events_base()


def _add(**over) -> dict:
    a = {
        "date": "2026-11-26",
        "org": "Example Utility",
        "sector": "Energy",
        "title": "Billing outage",
        "what": "Billing systems were down for a day.",
        "stated": "The utility blamed a vendor update.",
        "ai": "A trade outlet reported the update was written with an AI coding tool.",
        "link": "ai-tool",
        "sources": [{"outlet": "Example News", "date": "2026-11-27", "title": "Outage", "url": OK}],
    }
    a.update(over)
    return a


def _merge(proposal, seen=(OK,), auto=None, status=200):
    return er.merge(_base(), auto, proposal, TODAY, set(seen), check=lambda u: status)


def test_a_sourced_addition_is_kept_and_marked():
    auto, dec = _merge({"additions": [_add()], "updates": []})
    assert dec["added"] == ["2026-11-26|Example Utility"] and not dec["rejected"]
    d = indicators.events(auto)
    row = next(e for e in d["events"] if e["org"] == "Example Utility")
    assert row["auto_added"] == TODAY
    assert d["searched"] == TODAY and d["as_of"] == TODAY


def test_a_url_claude_did_not_see_is_rejected():
    auto, dec = _merge({"additions": [_add()], "updates": []}, seen=())
    assert not dec["added"]
    assert "search results" in dec["rejected"][0]["why"][0]


def test_a_dead_source_is_rejected_but_a_blocked_one_is_not():
    assert not _merge({"additions": [_add()], "updates": []}, status=404)[1]["added"]
    assert _merge({"additions": [_add()], "updates": []}, status=403)[1]["added"]


def test_bad_grade_future_date_and_duplicates_are_rejected():
    listed = _base()["events"][0]
    props = [
        _add(link="probably-ai"),
        _add(date="2027-01-01", org="Later"),
        _add(date=listed["date"], org=listed["org"]),
        _add(org="Other", sources=[dict(listed["sources"][0])]),
    ]
    seen = {OK, listed["sources"][0]["url"]}
    _, dec = _merge({"additions": props, "updates": []}, seen=seen)
    assert not dec["added"] and len(dec["rejected"]) == 4


def test_an_update_changes_a_listed_row_without_touching_the_curated_file():
    target = next(e for e in _base()["events"] if e["link"] == "speculated")
    k = er.key(target)
    upd = {
        "key": k,
        "reason": "The post-incident report was published.",
        "what": None,
        "stated": "The report blames a configuration change.",
        "ai": None,
        "link": "none",
        "new_sources": [{"outlet": "Org", "date": TODAY, "title": "Report", "url": OK}],
    }
    auto, dec = _merge({"additions": [], "updates": [upd]})
    assert dec["updated"] == [k]
    row = next(e for e in indicators.events(auto)["events"] if er.key(e) == k)
    assert row["link"] == "none" and row["stated"].startswith("The report")
    assert row["auto_update"]["reason"].startswith("The post-incident")
    assert row["sources"][-1]["url"] == OK
    assert next(e for e in _base()["events"] if er.key(e) == k)["link"] == "speculated"


def test_an_update_to_an_unknown_event_or_with_no_change_is_rejected():
    listed = _base()["events"][0]
    same = {
        "key": er.key(listed),
        "reason": "x",
        "what": None,
        "stated": listed["stated"],
        "ai": None,
        "link": None,
        "new_sources": [],
    }
    unknown = {**same, "key": "2026-01-01|Nobody"}
    _, dec = _merge({"additions": [], "updates": [same, unknown]})
    assert not dec["updated"] and len(dec["rejected"]) == 2


def test_runs_accumulate_and_a_second_run_does_not_re_add():
    auto, _ = _merge({"additions": [_add()], "updates": []})
    auto2, dec = _merge({"additions": [_add()], "updates": []}, auto=auto)
    assert not dec["added"] and len(auto2["runs"]) == 2
    assert sum(e["org"] == "Example Utility" for e in indicators.events(auto2)["events"]) == 1


def test_a_curated_row_wins_over_an_old_addition():
    auto, _ = _merge({"additions": [_add()], "updates": []})
    base = _base()
    base["events"].append({**_add(), "stated": "Curated wording."})
    rows = [e for e in indicators.apply_auto(base, auto)["events"] if e["org"] == "Example Utility"]
    assert len(rows) == 1 and rows[0]["stated"] == "Curated wording."


class _Stream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


class _Client:
    """Pauses once mid-search, then submits."""

    def __init__(self):
        self.calls = []
        usage = NS(input_tokens=10, output_tokens=5, server_tool_use=NS(web_search_requests=2))
        search = NS(type="web_search_tool_result", content=[NS(url=OK)])
        submit = NS(
            type="tool_use",
            name="submit_changes",
            input={"additions": [_add()], "updates": [], "notes": ""},
        )
        self.replies = [
            NS(stop_reason="pause_turn", content=[search], usage=usage, model=er.MODEL),
            NS(stop_reason="tool_use", content=[submit], usage=usage, model=er.MODEL),
        ]
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kw):
        self.calls.append(kw)
        return _Stream(self.replies[len(self.calls) - 1])


def test_the_search_loop_resumes_a_paused_turn_and_collects_urls():
    c = _Client()
    out = er.ask_claude(indicators.events(), TODAY, client=c)
    assert len(c.calls) == 2 and out["seen"] == [OK]
    assert out["usage"]["web_search_requests"] == 4 and out["usage"]["turns"] == 2
    assert c.calls[0]["model"] == "claude-opus-5-5"
    # a paused turn is resumed by resending, with no extra user message
    assert [m["role"] for m in c.calls[1]["messages"]] == ["user", "assistant"]
    assert er.merge(_base(), None, out["proposal"], TODAY, out["seen"], check=lambda u: 200)[1][
        "added"
    ]


def test_the_page_marks_what_the_search_added(sources_dir, tmp_path):
    from airisk.site import build_site

    auto, _ = _merge({"additions": [_add()], "updates": []})
    build_site(sources_dir, tmp_path / "s", history=[], events_auto=auto)
    index = (tmp_path / "s" / "index.html").read_text()
    assert "Example Utility" in index
    assert "Found by the weekly automated search on 2026-11-30" in index
    assert "searched again each week (last 2026-11-30)" in index


def test_claims_are_sourced_and_coded():
    d = indicators.claims()
    assert len(d["claims"]) >= 15 and d["disclosed"]
    for c in d["claims"]:
        assert c["outcome"] in indicators.CLAIM_OUTCOMES
        assert c["claim"]["source"]["url"].startswith("https://")
        assert c["outcome"] == "open" or c["official"]


def _upd(cid, outcome="non-ai", url=OK):
    return {
        "id": cid,
        "outcome": outcome,
        "by": "The company",
        "date": "2026-11-28",
        "finding": "A configuration error, not AI.",
        "reason": "Root-cause report published.",
        "source": {"outlet": "Org", "date": "2026-11-28", "title": "Report", "url": url},
    }


def test_the_search_can_settle_an_open_claim_only():
    tracked = indicators.claims()
    open_id = next(c["id"] for c in tracked["claims"] if c["outcome"] == "open")
    done_id = next(c["id"] for c in tracked["claims"] if c["outcome"] == "confirmed")
    auto, dec = er.merge(
        _base(),
        None,
        {"claim_updates": [_upd(open_id), _upd(done_id)]},
        TODAY,
        {OK},
        check=lambda u: 200,
        claims=tracked,
    )
    assert dec["resolved"] == [open_id]
    assert "already settled" in dec["rejected"][0]["why"][0]
    row = next(c for c in indicators.claims(auto)["claims"] if c["id"] == open_id)
    assert row["outcome"] == "non-ai" and row["auto_resolved"]["on"] == TODAY
    # a source the search did not see is refused
    _, dec2 = er.merge(
        _base(),
        None,
        {"claim_updates": [_upd(open_id, url="https://elsewhere.example/x")]},
        TODAY,
        {OK},
        check=lambda u: 200,
        claims=tracked,
    )
    assert not dec2["resolved"]


def test_the_page_shows_whether_the_blame_held_up(sources_dir, tmp_path):
    from airisk.site import build_site

    build_site(sources_dir, tmp_path / "s", history=[])
    index = (tmp_path / "s" / "index.html").read_text()
    paper = (tmp_path / "s" / "paper.html").read_text()
    assert 'id="held-up"' in index and "Did the AI blame hold up?" in index
    assert "2.9 Does the blame hold up?" in paper and "{{" not in paper
