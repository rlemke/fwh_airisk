"""The weekly search for outages and hacks blamed on AI.

``data/events.json`` is curated by hand. Once a week this asks Claude, with web
search, two questions: has anything new been blamed on AI since the list was
last searched, and has anything changed for an event already listed (a root
cause published, an official denial, a new investigation)? Claude answers by
calling one tool, ``submit_changes``. Nothing it says goes onto the page
until :func:`merge` has checked it:

- every field the page needs is present and the evidence grade is one of the six;
- every source URL is one that came up in Claude's own searches or fetches
  during this run, so a URL cannot be invented, and it does not answer 404/410;
- an addition is not already listed (same date and organisation, or a source
  already cited by a listed event);
- an update names a listed event and says why.

What passes is kept apart from the hand-curated file, in the domain store
(``events-auto.json``), and applied on top of it at build time. So a hand edit
to ``data/events.json`` is never overwritten, and the page marks every row the
search added or changed until a person moves it into the curated file.
Each run's proposal, decisions and token use are kept in ``events-log/``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from . import indicators

MODEL = "claude-opus-5-5"
#: Web search is billed per search, so both server tools are capped.
MAX_SEARCHES = 30
MAX_FETCHES = 20
MAX_TURNS = 12
KEEP_RUNS = 104

_SOURCE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outlet", "date", "title", "url"],
    "properties": {
        "outlet": {"type": "string"},
        "date": {"type": "string", "description": "YYYY-MM-DD, or YYYY-MM"},
        "title": {"type": "string"},
        "url": {"type": "string", "description": "Exactly as it appeared in a search result"},
    },
}
_NULLABLE = {"type": ["string", "null"]}

SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_changes",
    "description": (
        "Submit this week's changes to the list of outages and hacks blamed on AI. "
        "Call it exactly once, at the end, with empty lists if nothing qualifies."
    ),
    "strict": True,
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["additions", "updates", "notes"],
        "properties": {
            "additions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "date",
                        "org",
                        "sector",
                        "title",
                        "what",
                        "stated",
                        "ai",
                        "link",
                        "sources",
                    ],
                    "properties": {
                        "date": {"type": "string", "description": "YYYY-MM-DD the event began"},
                        "org": {"type": "string"},
                        "sector": {"type": "string"},
                        "title": {"type": "string"},
                        "what": {"type": "string"},
                        "stated": {"type": "string"},
                        "ai": {"type": "string"},
                        "link": {"type": "string", "enum": list(indicators.EVENT_LINKS)},
                        "sources": {"type": "array", "items": _SOURCE},
                    },
                },
            },
            "updates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["key", "reason", "what", "stated", "ai", "link", "new_sources"],
                    "properties": {
                        "key": {"type": "string", "description": "The listed event's key"},
                        "reason": {"type": "string"},
                        "what": _NULLABLE,
                        "stated": _NULLABLE,
                        "ai": _NULLABLE,
                        "link": {
                            "anyOf": [
                                {"type": "string", "enum": list(indicators.EVENT_LINKS)},
                                {"type": "null"},
                            ]
                        },
                        "new_sources": {"type": "array", "items": _SOURCE},
                    },
                },
            },
            "notes": {"type": "string"},
        },
    },
}

SYSTEM = """You maintain one section of a public web page, the AI Risk Clock: a list of \
outages and hacks that someone has publicly blamed on AI. Each row keeps three things apart: \
what happened, the cause the organisation itself states, and who links it to AI and on what \
evidence. Every row carries a grade of the evidence for an AI link:

{grades}

Your job this week, using web search:
1. Find events since {since} that belong on the list: a significant outage, breach or hack \
at a government body, a large business, or critical infrastructure, where an official, an \
investigator, the organisation, an AI developer, or a reputable outlet has publicly linked it \
to AI (AI acting on its own, attackers using AI, an AI tool in the failure, rushed fixes for \
AI-found flaws, or a public claim that AI was behind it). Also include an incident an AI \
developer reports about its own systems acting on their own. Do not include product launches, \
research demos with no real-world victim, or opinion pieces about AI risk in general.
2. For each listed event, check whether anything has changed: a root cause or post-incident \
report published, an official confirming or denying an AI link, new investigation findings. \
Propose an update only when new reporting changes what the row says.

Rules:
- Cite only pages you found in this session's searches or fetched, with the URL exactly as \
it appeared. Prefer the organisation's own statement, official advisories, and established \
news outlets. Every addition needs at least one such source.
- Grade conservatively: the grade is what the evidence shows, not what commentators suggest. \
An unsourced or anonymous claim is at most "patch-rush" or "speculated".
- Write plainly and neutrally, in the style of the existing rows: short sentences, attribute \
every claim to who made it, no speculation of your own. "stated" is the organisation's own \
explanation, or says that it has given none.
- Do not re-add an event that is already listed; update it instead.
- When you are done, call submit_changes exactly once. Empty lists are a good answer for a \
quiet week."""


def key(e: dict) -> str:
    return f"{e['date']}|{e['org']}"


def today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


def prompt(events: dict, today: str) -> str:
    rows = [
        {
            "key": key(e),
            "title": e["title"],
            "stated": e["stated"],
            "ai": e["ai"],
            "link": e["link"],
            "sources": [s["url"] for s in e["sources"]],
        }
        for e in events["events"]
    ]
    return (
        f"Today is {today}. The list was last searched on {events['as_of']}.\n\n"
        "The events listed now (one JSON object per line):\n"
        + "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        + "\n\nSearch for new events and for changes to these, then call submit_changes."
    )


def system_prompt(events: dict, since: str) -> str:
    grades = "\n".join(
        f'- "{k}": {events["links"][k][0]}. {events["links"][k][1]}' for k in indicators.EVENT_LINKS
    )
    return SYSTEM.format(grades=grades, since=since)


def _seen_urls(content: list) -> set[str]:
    """Every URL a search result or fetch returned in this response."""
    out: set[str] = set()
    for b in content:
        t = getattr(b, "type", "")
        c = getattr(b, "content", None)
        if t == "web_search_tool_result" and isinstance(c, list):
            out.update(u for u in (getattr(r, "url", None) for r in c) if u)
        elif t == "web_fetch_tool_result" and getattr(c, "url", None):
            out.add(c.url)
    return out


def ask_claude(events: dict, today: str, client: Any = None, log: Callable | None = None) -> dict:
    """Run the search; return Claude's proposal, the URLs it saw, and token use."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    tools = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": MAX_FETCHES},
        SUBMIT_TOOL,
    ]
    system = system_prompt(events, events["as_of"])
    messages: list[dict] = [{"role": "user", "content": prompt(events, today)}]
    seen: set[str] = set()
    usage: dict[str, Any] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "web_search_requests": 0,
        "turns": 0,
    }
    for _ in range(MAX_TURNS):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=system,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            resp = stream.get_final_message()
        usage["turns"] += 1
        u = resp.usage
        usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
        usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
        stu = getattr(u, "server_tool_use", None)
        usage["web_search_requests"] += getattr(stu, "web_search_requests", 0) or 0
        usage["model"] = getattr(resp, "model", MODEL)
        seen |= _seen_urls(resp.content)
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"the model declined: {getattr(resp, 'stop_details', None)}")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("the response hit max_tokens before submitting")
        for b in resp.content:
            if getattr(b, "type", "") == "tool_use" and b.name == "submit_changes":
                proposal = b.input if isinstance(b.input, dict) else json.loads(b.input)
                if log:
                    log(
                        f"search done in {usage['turns']} turn(s): "
                        f"{len(proposal.get('additions') or [])} proposed additions, "
                        f"{len(proposal.get('updates') or [])} proposed updates, "
                        f"{len(seen)} URLs seen",
                        level="info",
                    )
                return {"proposal": proposal, "seen": sorted(seen), "usage": usage}
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "pause_turn":
            messages.append(
                {
                    "role": "user",
                    "content": "Call submit_changes now with what you found "
                    "(empty lists if nothing qualifies).",
                }
            )
    raise RuntimeError(f"no submit_changes call after {MAX_TURNS} turns")


def url_status(url: str) -> int:
    """HTTP status of a GET, 0 if it could not connect. Only 404/410 reject a source."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; facetwork-airisk/1.0)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001 - a timeout or TLS failure says nothing about the page
        return 0


def _sources(raw: list, seen: set[str], check: Callable[[str], int], why: list[str]) -> list[dict]:
    out = []
    for s in raw or []:
        url = (s.get("url") or "").strip()
        if not url.startswith("https://"):
            why.append(f"not https: {url}")
        elif url not in seen:
            why.append(f"not in this run's search results: {url}")
        elif check(url) in (404, 410):
            why.append(f"answers 404/410: {url}")
        elif not (s.get("outlet") and s.get("title")):
            why.append(f"source without outlet or title: {url}")
        else:
            out.append({k: s[k] for k in ("outlet", "date", "title", "url")})
    return out


def merge(
    base: dict,
    auto: dict | None,
    proposal: dict,
    today: str,
    seen: set[str] | list[str],
    check: Callable[[str], int] = url_status,
) -> tuple[dict, dict]:
    """Check Claude's proposal and fold what passes into the overlay.

    ``base`` is the hand-curated file as written. Returns the new overlay and a
    record of every decision, rejections with their reasons.
    """
    seen = set(seen)
    auto = json.loads(json.dumps(auto or {}))
    auto.setdefault("additions", [])
    auto.setdefault("updates", {})
    auto.setdefault("runs", [])
    listed = {key(e): e for e in base["events"]}
    added_by_key = {key(e): e for e in auto["additions"] if key(e) not in listed}
    cited = {s["url"]: k for k, e in {**listed, **added_by_key}.items() for s in e["sources"]}
    decisions: dict[str, list] = {"added": [], "updated": [], "rejected": []}

    for a in proposal.get("additions") or []:
        name = f"{a.get('date', '?')}|{a.get('org', '?')}"
        why: list[str] = []
        for k in ("date", "org", "sector", "title", "what", "stated", "ai"):
            if not (a.get(k) or "").strip():
                why.append(f"missing {k}")
        if a.get("link") not in indicators.EVENT_LINKS:
            why.append(f"unknown grade {a.get('link')!r}")
        d = a.get("date") or ""
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            why.append(f"date not YYYY-MM-DD: {d!r}")
        else:
            if d > today:
                why.append("date in the future")
        if name in listed or name in added_by_key:
            why.append("already listed")
        dup = next(
            (cited[s.get("url")] for s in a.get("sources") or [] if s.get("url") in cited), None
        )
        if dup:
            why.append(f"cites a source already cited by {dup}")
        srcs = _sources(a.get("sources"), seen, check, why) if not why else []
        if not why and not srcs:
            why.append("no usable source")
        if why:
            decisions["rejected"].append({"addition": name, "why": why})
            continue
        row = {k: a[k].strip() for k in ("date", "org", "sector", "title", "what", "stated", "ai")}
        row.update(link=a["link"], sources=srcs, auto_added=today)
        auto["additions"].append(row)
        added_by_key[name] = row
        for s in srcs:
            cited[s["url"]] = name
        decisions["added"].append(name)

    for u in proposal.get("updates") or []:
        k = u.get("key") or ""
        why = []
        if k not in listed and k not in added_by_key:
            why.append("no listed event has this key")
        if not (u.get("reason") or "").strip():
            why.append("no reason given")
        if u.get("link") is not None and u.get("link") not in indicators.EVENT_LINKS:
            why.append(f"unknown grade {u.get('link')!r}")
        srcs = _sources(u.get("new_sources"), seen, check, why) if not why else []
        if why:
            decisions["rejected"].append({"update": k, "why": why})
            continue
        current = added_by_key.get(k) or listed[k]
        prior = auto["updates"].get(k, {})
        fields = {
            f: u[f].strip()
            for f in ("what", "stated", "ai", "link")
            if (u.get(f) or "").strip() and u[f].strip() != (prior.get(f) or current.get(f))
        }
        have = {s["url"] for s in current["sources"]} | {s["url"] for s in prior.get("sources", [])}
        srcs = [s for s in srcs if s["url"] not in have]
        if not fields and not srcs:
            decisions["rejected"].append({"update": k, "why": ["changes nothing"]})
            continue
        if k in added_by_key:
            row = added_by_key[k]
            row.update(fields)
            row["sources"] = row["sources"] + srcs
            row["auto_update"] = {"on": today, "reason": u["reason"].strip()}
        else:
            entry = {**prior, **fields}
            entry["sources"] = prior.get("sources", []) + srcs
            entry.update(on=today, reason=u["reason"].strip())
            auto["updates"][k] = entry
        decisions["updated"].append(k)

    auto["runs"] = (
        auto["runs"]
        + [
            {
                "date": today,
                "added": len(decisions["added"]),
                "updated": len(decisions["updated"]),
                "rejected": len(decisions["rejected"]),
            }
        ]
    )[-KEEP_RUNS:]
    return auto, decisions


def refresh(log: Callable | None = None, client: Any = None) -> dict:
    """One weekly run: search, check, then write the overlay and the run's log."""
    from facetwork.domains.storage import is_remote

    from .storage import S, events_auto_path, events_log_path

    today = today_utc()
    base = indicators.events_base()
    ap = events_auto_path()
    auto = json.loads(S.read_text(ap)) if S.exists(ap) else None
    asked = ask_claude(indicators.apply_auto(base, auto), today, client=client, log=log)
    new_auto, decisions = merge(base, auto, asked["proposal"], today, asked["seen"])
    indicators.validate_events(indicators.apply_auto(base, new_auto))
    lp = events_log_path(today)
    for p in (ap, lp):
        if not is_remote(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
    S.write_text(
        lp,
        json.dumps({"date": today, **asked, "decisions": decisions}, indent=1, ensure_ascii=False),
    )
    S.write_text(ap, json.dumps(new_auto, indent=1, ensure_ascii=False, sort_keys=True))
    if log:
        for r in decisions["rejected"]:
            what = r.get("addition") or r.get("update")
            log(f"rejected {what}: {'; '.join(r['why'])}", level="warning")
        log(
            f"added {len(decisions['added'])}, updated {len(decisions['updated'])}, "
            f"rejected {len(decisions['rejected'])}",
            level="info",
        )
    return {
        "added": len(decisions["added"]),
        "updated": len(decisions["updated"]),
        "rejected": len(decisions["rejected"]),
        "as_of": today,
        "log_path": lp,
        "decisions": decisions,
        "usage": asked["usage"],
    }
