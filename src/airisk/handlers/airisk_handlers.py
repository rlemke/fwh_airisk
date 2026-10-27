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
    from ..storage import S, history_path

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
    dest = join(S.maps_root(), "site", "airisk")
    log = params.get("_step_log")
    with tempfile.TemporaryDirectory(prefix="airisk_") as tmp:
        stamps = {s["key"]: s["stamp"] for s in srcs if s.get("stamp")}
        out = build_site(local, tmp, history=history, log=log, stamps=stamps)
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


_DISPATCH: dict[str, Callable[[dict], dict]] = {
    "airisk.data.Sources": handle_sources,
    "airisk.site.Build": handle_site_build,
}


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
        )


def register_poller(poller) -> None:
    """Register every facet with an AgentPoller."""
    for facet_name, handler in _DISPATCH.items():
        poller.register(facet_name, handler)
