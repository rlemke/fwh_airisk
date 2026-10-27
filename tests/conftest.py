"""Small synthetic copies of every source file, so the tests run offline."""

from __future__ import annotations

import csv
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

MODELS_HEADER = [
    "Model",
    "Organization",
    "Publication date",
    "Training compute (FLOP)",
    "Training compute (FLOP) notes",
    "Training compute cost (2023 USD)",
]


def _models_csv(path: Path) -> None:
    """Compute doubling every 6 months 2016-2022, then every 4 months after."""
    rows = []
    for i in range(40):
        y = 2016 + i * 0.25
        doublings = (min(y, 2022) - 2016) * 2 + max(0.0, y - 2022) * 3
        flop = 1e20 * 2**doublings
        month = int((y % 1) * 12) + 1
        rows.append(
            [f"M{i}", "Lab", f"{int(y)}-{month:02d}-15", f"{flop:.4g}", "", f"{flop / 1e17:.4g}"]
        )
        rows.append([f"S{i}", "Small", f"{int(y)}-{month:02d}-20", f"{flop / 1000:.4g}", "", ""])
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(MODELS_HEADER)
        w.writerows(rows)


def _bench_csv(rows: list[list], header: list[str]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def _bench_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "benchmarks/epoch_capabilities_index/eci_scores.csv",
            _bench_csv(
                [
                    [
                        f"m{i}",
                        f"Model {i}",
                        110 + i * 2,
                        f"{2023 + i // 4}-{(i % 4) * 3 + 1:02d}-01",
                    ]
                    for i in range(16)
                ],
                ["Model", "Display name", "eci", "date"],
            ),
        )
        z.writestr(
            "benchmarks/metr_time_horizons_external.csv",
            _bench_csv(
                [
                    [f"a{i}", 2 ** (i * 0.5), f"{2022 + i // 4}-{(i % 4) * 3 + 1:02d}-01"]
                    for i in range(18)
                ],
                ["Model version", "Time horizon", "Release date"],
            ),
        )
        z.writestr(
            "benchmarks/cybench_external.csv",
            _bench_csv(
                [
                    [f"c{i}", 0.05 * i, f"{2024 + i // 6}-{(i % 6) * 2 + 1:02d}-01"]
                    for i in range(15)
                ],
                ["Model version", "Unguided % Solved", "Release date"],
            ),
        )
        z.writestr(
            "benchmarks/rli_external.csv",
            _bench_csv(
                [[f"r{i}", 0.01 * 1.3**i, f"2025-{i + 1:02d}-01"] for i in range(10)],
                ["Model version", "Score", "Release date"],
            ),
        )
        z.writestr(
            "benchmarks/gpqa_diamond.csv",
            _bench_csv(
                [
                    [f"g{i}", 0.3 + 0.04 * i, f"{2023 + i // 4}-{(i % 4) * 3 + 1:02d}-01"]
                    for i in range(16)
                ],
                ["Model version", "mean_score", "Release date"],
            ),
        )


def _investment_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["entity", "code", "year", "private_investment"])
        for y in range(2013, 2026):
            w.writerow(["World", "OWID_WRL", y, int(1e10 * 1.3 ** (y - 2013))])
            w.writerow(["China", "CHN", y, int(1e9 * 1.2 ** (y - 2013))])


def _incident_tar(path: Path) -> None:
    inc = ["_id,incident_id,date,title"]
    mit = ["Namespace,Incident ID,Published,Risk Domain,Risk Subdomain,Entity,Timing,Intent"]
    iid = 0
    for year, n in ((2022, 10), (2023, 20), (2024, 40), (2025, 60), (2026, 30)):
        for k in range(n):
            iid += 1
            month = (k % 9) + 1  # 2026 runs only to September
            inc.append(f"x{iid},{iid},{year}-{month:02d}-10,Incident {iid}")
            if k % 5:
                dom = [
                    "4. Malicious Actors & Misuse",
                    "3. Misinformation",
                    "7. AI System Safety, Failures, & Limitations",
                ][k % 3]
                mit.append(f'MIT,{iid},True,"{dom}",x,AI,Post-deployment,Intentional')
    with tarfile.open(path, "w:bz2") as tf:
        for name, body in (("incidents.csv", inc), ("classifications_MIT.csv", mit)):
            data = ("\n".join(body) + "\n").encode()
            info = tarfile.TarInfo(f"mongodump_full_snapshot/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


CLOCK = """{| class="wikitable"
|-
| 1947
| 7
| 23:53
| 0
| align="left" | The initial setting of the Doomsday Clock.
|-
| 1991
| 17
| 23:43
| +7
| align="left" | The [[START I|first Strategic Arms Reduction Treaty]] is signed.<ref>x</ref>
|-
| 2020
| data-sort-value="1.67" | {{frac|1|2|3}}<br/>(100 s)
| 23:58:20
| −20 s
| align="left" | Nuclear risk, climate, and disruptive technologies such as [[artificial intelligence]].
|-
| 2026
| data-sort-value="1.42" | {{frac|1|5|12}}<br/>(85 s)
| 23:58:35
| −4 s
| align="left" | Wars, proliferation, and advancing technologies.
|}
"""


@pytest.fixture(scope="session")
def sources_dir(tmp_path_factory) -> dict[str, str]:
    d = tmp_path_factory.mktemp("airisk_sources")
    _models_csv(d / "models.csv")
    _bench_zip(d / "bench.zip")
    _investment_csv(d / "inv.csv")
    _incident_tar(d / "backup-20261026101519.tar.bz2")
    (d / "clock.wiki").write_text(CLOCK, encoding="utf-8")
    return {
        "epoch_models": str(d / "models.csv"),
        "epoch_benchmarks": str(d / "bench.zip"),
        "owid_investment": str(d / "inv.csv"),
        "aiid_snapshot": str(d / "backup-20261026101519.tar.bz2"),
        "doomsday_clock": str(d / "clock.wiki"),
    }
