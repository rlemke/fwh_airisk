"""AI risk domain — the ways AI could harm humanity, and what is measured about each.

There is no measured probability of an AI catastrophe, so this domain does
not invent one. It tracks the open, dated series that bear on each risk
pathway — training compute, general capability, how long a task an AI agent
can finish on its own, offensive-cyber skill, share of real paid work it can
do, money flowing in, reported AI incidents by risk domain, and what AI
researchers say when surveyed — and reports the PACE of each: its current
doubling time or yearly gain, against the same measure two years earlier.

The site it renders is a paper whose numbers are recomputed from the data on
every refresh, so the text and charts move as the world does.

Discovered by the Facetwork runner via the ``facetwork.domains`` entry point::

    [project.entry-points."facetwork.domains"]
    airisk = "airisk:domain"
"""

from __future__ import annotations

from pathlib import Path

from facetwork.domains import DomainPackage

from .handlers import register_all_registry_handlers

domain = DomainPackage(
    name="airisk",
    ffl_dir=Path(__file__).parent / "ffl",
    register_handlers=register_all_registry_handlers,
)
