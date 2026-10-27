# fwh_airisk — the AI Risk Clock

A [Facetwork](https://github.com/rlemke/facetwork) domain. It sets out the ways AI could harm humanity, as the research literature describes them, and tracks how fast the measured drivers of each pathway are moving. The output is a static site of three pages:

- **The clock** (`index.html`) — a pace board. For each indicator: the latest best value, its pace over the last window against the window before, and whether it is accelerating, steady or slowing. Beside it, the Doomsday Clock.
- **The paper** (`paper.html`) — *How AI Could Harm Humanity — and What the Numbers Say*. Every number in the text is filled in from the data at build time, so the paper moves when the indicators do.
- **The data** (`data.html`) — every indicator in full. It shows every model measured, the frontier, both fitted paces, how the pace itself has changed quarter by quarter, the milestones the current pace points to, and the reading recorded at each refresh.

It does **not** compute a probability of doom. No data supports one, and the paper explains why.

## FFL at a glance

```ffl
namespace demo {
    use airisk.workflows

    // Fetch every source (only what changed upstream) and rebuild the site.
    workflow Refresh() => (accelerating: Json, through: String) andThen {
        up = airisk.workflows.Update()
        yield Refresh(accelerating = up.accelerating, through = up.through)
    }
}
```

More scenarios are in [docs/ffl-examples.md](docs/ffl-examples.md). The scheduled job is `airisk.publish.UpdateSite` ([ffl/airisk_site.ffl](src/airisk/ffl/airisk_site.ffl)): `Update`, then one publish of the bundle `ai-risk/` through the shared Pages publisher.

## Pathways and indicators

| Pathway | Indicator | Source |
|---|---|---|
| Raw capability | Training compute of frontier models; Epoch Capabilities Index | Epoch AI |
| Loss of control | METR 50% task time horizon (autonomy) | METR, via Epoch AI |
| Misuse: cyberattacks | Cybench, share solved with no hints | Epoch AI |
| Misuse: bio and chemical weapons | GPQA Diamond (a proxy for expert science knowledge only) | Epoch AI |
| Economic disempowerment | Remote Labor Index, share of real freelance projects delivered | Epoch AI |
| Race dynamics | Private investment in AI; cost of a frontier training run | Our World in Data / Stanford AI Index; Epoch AI |
| Harms already happening | Reported incidents per year by MIT risk domain | AI Incident Database |
| Expert judgement | Expert Survey on Progress in AI; the Doomsday Clock | AI Impacts (`data/surveys.json`); Bulletin of the Atomic Scientists via Wikipedia |

All sources are open and need no key. Each is fetched with the built-in `fw.http.Fetch`, so a refresh downloads only what changed. The AI Incident Database snapshot (~120 MB) is resolved weekly and stored under one name, so old snapshots do not accumulate.

## Method

- **Frontier.** The latest best value is the highest measured so far. Compute and cost are fitted on models that were in the top ten when published, which is Epoch AI's frontier rule. Benchmarks are fitted on the models that set a new record.
- **Pace.** Growing quantities are fitted in log₂ against time, which gives a doubling time. Bounded scores are fitted linearly, in points per year. The recent window ends at the latest measurement, and the prior window is the same length just before it. Each window needs at least three points.
- **Verdict.** *Accelerating* means the recent pace is at least 25% faster than the prior one; *slowing* means at least 20% slower.
- **Milestones.** The recent fit is extended to round targets, such as a 40-hour work week of autonomous work. These are extrapolations, not forecasts. When the line passes a target before any measured model does, the site says so rather than hiding it.
- **Determinism.** Pages depend only on the data, never on the build clock. An unchanged week therefore renders identical bytes, and the publisher commits nothing.
- **History.** Each build records a compact reading in `history.json` in the domain's cache. A row is appended only when a reading changed.

## Limits

- No open dataset tracks the mitigation side over time: safety research spending, tested safeguards, compute oversight, or rates of deceptive behaviour in deployment. The board shows how fast the drivers move, not whether the brakes keep up.
- No open series tracks biological uplift, autonomous-weapons deployment or AI in nuclear command and control. GPQA Diamond is a knowledge proxy only.
- Incident counts measure reports, so they rise with attention. The year in progress always looks low because reports arrive late.
- The survey question wording changed between rounds, and nothing newer than the 2023 round is published. Add a round to `data/surveys.json` when one appears.
- Benchmarks near their ceiling (Cybench, GPQA) stop measuring progress even while the capability they track keeps growing.

## Run it

```bash
pip install -e ".[test]"
pytest -q                       # offline, synthetic fixtures
fw runner start --domain airisk -- --topics 'airisk.*'
fw ffl run --primary src/airisk/ffl/airisk.ffl --library <facetwork>/facetwork/ffl/http.ffl \
    --workflow airisk.workflows.Update
```

Scheduled refresh: `fw svc airisk-update --install` in the facetwork repo. It runs daily and submits `airisk.publish.UpdateSite`.
