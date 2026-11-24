"""Thin dispatchers for the AI risk facets.

One ``handle(payload)`` entry point with a ``_DISPATCH`` table, because the
runner's handler cache is keyed on (module, entrypoint): several facets sharing
a module must share one entrypoint.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import sources


def _json(value: Any, default: Any) -> Any:
    """FFL may hand structured values over as JSON text."""
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def handle_sources(params: dict[str, Any]) -> dict[str, Any]:
    out = sources.plan()
    log = params.get("_step_log")
    if log:
        snap = next(s for s in out if s["key"] == "aiid_snapshot")
        log(
            f"{len(out)} files to check; incident snapshot {snap['url'].rsplit('/', 1)[-1]}",
            level="info",
        )
    return {"sources": out, "count": len(out), "user_agent": sources.USER_AGENT}


def handle_site_build(params: dict[str, Any]) -> dict[str, Any]:
    """Render the site locally, copy it to the maps store, record the reading.

    Staged locally because an object store has no partial writes. The refresh
    history is written last, after the pages, so a crash mid-copy leaves the
    previous history and the next run re-records this reading.
    """
    from facetwork.domains.storage import is_remote, join

    from ..site import build_site
    from ..storage import S, events_auto_path, history_path

    srcs = _json(params.get("sources"), [])
    paths = _json(params.get("paths"), [])
    if len(srcs) != len(paths):
        raise ValueError(f"{len(srcs)} sources but {len(paths)} fetched paths")
    local = {s["key"]: S.localize(p) for s, p in zip(srcs, paths)}
    missing = {
        "epoch_models",
        "epoch_benchmarks",
        "owid_investment",
        "aiid_snapshot",
        "doomsday_clock",
    } - set(local)
    if missing:
        raise ValueError(f"missing sources: {sorted(missing)}")
    hp = history_path()
    history = json.loads(S.read_text(hp)) if S.exists(hp) else []
    ap = events_auto_path()
    events_auto = json.loads(S.read_text(ap)) if S.exists(ap) else None
    dest = join(S.maps_root(), "site", "airisk")
    log = params.get("_step_log")
    with tempfile.TemporaryDirectory(prefix="airisk_") as tmp:
        stamps = {s["key"]: s["stamp"] for s in srcs if s.get("stamp")}
        out = build_site(
            local, tmp, history=history, log=log, stamps=stamps, events_auto=events_auto
        )
        for rel in out["paths"]:
            target = join(dest, rel)
            if not is_remote(target):
                os.makedirs(os.path.dirname(target), exist_ok=True)
            S.write_bytes(target, Path(tmp, rel).read_bytes())
    if not is_remote(hp):
        os.makedirs(os.path.dirname(hp), exist_ok=True)
    S.write_text(hp, json.dumps(out["history"], indent=1, sort_keys=True))
    if log:
        log(
            f"data through {out['through']}; accelerating: {', '.join(out['accelerating']) or 'none'}",
            level="info",
        )
    return {
        "output_dir": dest,
        "files": out["files"],
        "bytes": out["bytes"],
        "through": out["through"],
        "summary": out["summary"],
        "accelerating": out["accelerating"],
    }


def handle_events_refresh(params: dict[str, Any]) -> dict[str, Any]:
    """The weekly search for outages and hacks blamed on AI (see events_refresh)."""
    from ..events_refresh import refresh

    out = refresh(log=params.get("_step_log"))
    return {k: out[k] for k in ("added", "updated", "resolved", "rejected", "as_of", "log_path")}


_DISPATCH: dict[str, Callable[[dict], dict]] = {
    "airisk.data.Sources": handle_sources,
    "airisk.site.Build": handle_site_build,
    "airisk.events.Refresh": handle_events_refresh,
}

#: The weekly search calls the Claude API. Declared on the registration so a
#: runner without the key does not advertise the facet and never claims it.
REQUIRES_ENV = {"airisk.events.Refresh": ["ANTHROPIC_API_KEY"]}


def handle(payload: dict) -> dict:
    facet = payload.get("_facet_name", "")
    handler = _DISPATCH.get(facet)
    if handler is None:
        raise ValueError(f"Unknown facet: {facet}")
    return handler(payload)


def register_handlers(runner) -> None:
    """Register every facet with a RegistryRunner, all through ``handle``."""
    for facet_name in _DISPATCH:
        runner.register_handler(
            facet_name=facet_name,
            module_uri=f"file://{os.path.abspath(__file__)}",
            entrypoint="handle",
            **(
                {"metadata": {"requires_env": REQUIRES_ENV[facet_name]}}
                if facet_name in REQUIRES_ENV
                else {}
            ),
        )


def register_poller(poller) -> None:
    """Register every facet with an AgentPoller."""
    for facet_name, handler in _DISPATCH.items():
        poller.register(facet_name, handler)
