# LP Lens: Private Markets Fund Performance Analytics Platform

Fund-level private markets reporting — commitments, capital calls, distributions and NAV — from
generated source data through a warehouse to a Power BI semantic model and a web dashboard.

> **Status: In development — Phase 0 scaffold.**
> Every section below is a placeholder and says so. Nothing here reports a result that has not
> been measured, and there is no deployed artifact to link to yet.

## Overview

*Placeholder.*

To be written: the one-line value statement, the dashboard link and screenshots. No link exists
yet because no dashboard has been built.

## Architecture

*Placeholder.*

Intended shape. The generator stage is built; everything downstream of `data/raw` is not:

```
seeded synthetic generator
  -> data/raw/*.parquet
  -> Snowflake RAW
  -> dbt: staging -> intermediate -> marts
  -> Power BI semantic model (Import) + Streamlit dashboard
```

Both presentation layers are intended to read the same marts, so a number shown in Power BI and
the same number on the web dashboard come from one definition rather than two implementations.

## Synthetic data

Private markets fund-level data is not publicly available at the LP position level, so LP Lens
generates its own. **All of it is fabricated** — no manager, fund or investor in the output is a
real entity, and no figure is a real reported number.

```bash
python -m lp_lens.generate --config configs/generator.yaml --out data/raw
```

One seed in `configs/generator.yaml` drives every draw, and the same seed with the same config
produces byte-identical Parquet. Output goes to `data/raw/`, which is gitignored — generated data
is fully determined by the config and the code, so committing it would store something already
reproducible.

| Table | Grain | Rows |
|---|---|---|
| `managers` | one row per GP | 25 |
| `funds` | one row per fund | 60 |
| `investors` | one row per LP | 12 |
| `commitments` | investor × fund | 156 |
| `cash_flows` | one row per transaction | 3,078 |
| `nav` | fund × investor × quarter end | 4,454 |
| `fx_rates` | date × currency pair | 5,295 |
| `public_index` | date × index | 5,295 |

The two fact grains are worth noting, because they are the shape the replaced equities project did
not have: `cash_flows` is irregular, with a row only where a transaction landed, while `nav` is a
regular quarterly grid — and both are keyed on a *pair* of entities rather than a single
instrument. Amounts are unsigned magnitudes, with `flow_type` carrying the direction. Fund outcomes
are drawn per strategy so the book spans loss-making to top quartile, and NAV is derived from
cumulative paid-in and distributions rather than drawn, which is what makes it trace a J-curve.

[`src/lp_lens/generate/README.md`](src/lp_lens/generate/README.md) documents the entities, the
sign convention, the lifecycle and outcome model, and every invariant the generator enforces.

## Data model

*Placeholder — the star schema and the marts are Phase 2.*

The source entities and their grains are documented under [Synthetic data](#synthetic-data) above.
Still to be documented: the star schema, and the declared grain of every mart.

## Metrics definitions

*Placeholder.*

To be documented as a table of formula, grain, as-of convention and net-vs-gross treatment for
commitment, paid-in, unfunded, distributions, NAV, DPI, RVPI, TVPI, net IRR and KS-PME.

Two conventions will be stated explicitly rather than assumed, because both are easy to get
silently wrong: TVPI is a ratio of sums, never an average of ratios; and an IRR that fails to
converge is NULL, never 0.

## Dashboards

*Placeholder.*

To be built: a Power BI semantic model and report (PBIP / TMDL / PBIR), and a Streamlit dashboard
over the same marts so the work is viewable without installing Power BI Desktop. `powerbi/`
currently holds an empty PBIP scaffold only, described in [`powerbi/README.md`](powerbi/README.md).

## CI/CD

*Placeholder.*

`.github/workflows/ci.yml` runs on every pull request and on pushes to `main`. Today it installs
the `dev` extra and runs ruff and pytest — that is the whole workflow. Still to be added: sqlfluff,
a dbt build on both engines, a deferred build into a PR-specific Snowflake schema, and Best
Practice Analyzer checks on the semantic model. `.pre-commit-config.yaml` mirrors the lint half of
that gate locally.

## How to run

*Placeholder — extended as each phase lands. What works today:*

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
pytest

# Generate the synthetic source data into data/raw/ (gitignored).
python -m lp_lens.generate --config configs/generator.yaml --out data/raw
```

Credentials, once Snowflake enters the picture, come only from environment variables.

## Design decisions

*Placeholder.*

Two decisions already made and acted on:

- **Business logic lives in dbt, not DAX.** Metrics are to be computed once in the warehouse, with
  the semantic model only aggregating them. The audited predecessor project computed rolling
  windows inside DAX; [`docs/AUDIT.md`](docs/AUDIT.md) section 3 records why that is the pattern
  being avoided.
- **The first commit on `main` is the unmodified upstream project.** That makes the diff from it an
  exact record of what is original here, rather than something a reader has to take on trust.

## Attribution

This repository began from a fork of another MIT-licensed project and reuses a small number of its
engineering patterns. Each adapted file is listed individually, with every change described, in
[ATTRIBUTION.md](ATTRIBUTION.md). The domain layer shares nothing — the upstream project analyses
public equities.

[`docs/AUDIT.md`](docs/AUDIT.md) is the pre-work audit of what the inherited repository actually
contained, with a file path as evidence for every claim.

## License

MIT. See [LICENSE](LICENSE), which carries both the original copyright notice and this project's.
