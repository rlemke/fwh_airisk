"""Where the AI risk domain keeps its downloads: the shared domain storage layer.

On the fleet this is the object store (``s3://…/cache/airisk``); on a laptop a
local directory. Raw files are kept as fetched.
"""

from __future__ import annotations

from facetwork.domains.storage import domain_storage, join

S = domain_storage("airisk", layout="flat")


def raw_path(name: str) -> str:
    return join(S.cache_root(), "raw", name)


def history_path() -> str:
    """The pace readings of every refresh, so the site can show how they move."""
    return join(S.cache_root(), "history.json")
