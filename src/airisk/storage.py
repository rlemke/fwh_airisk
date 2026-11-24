"""Where the AI risk domain keeps its downloads: the shared domain storage layer.

On the fleet this is the object store (``s3://…/cache/airisk``); on a laptop a
local directory. Raw files are kept as fetched.
"""

from __future__ import annotations

from facetwork.domains.storage import domain_storage, join

S = domain_storage("airisk", layout="flat")


def raw_path(name: str) -> str:
    return join(S.cache_root(), "raw", name)


def events_auto_path() -> str:
    """What the weekly search added to or changed in the curated events list."""
    return join(S.cache_root(), "events-auto.json")


def events_log_path(day: str) -> str:
    """One weekly search: Claude's proposal, the URLs it saw, every decision."""
    return join(S.cache_root(), "events-log", f"{day}.json")


def history_path() -> str:
    """The pace readings of every refresh, so the site can show how they move."""
    return join(S.cache_root(), "history.json")
