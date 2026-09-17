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

Intended shape. None of it is built beyond the scaffolding in this repository:

```
seeded synthetic generator
  -> data/raw/*.parquet
  -> Snowflake RAW
  -> dbt: staging -> intermediate -> marts
  -> Power BI semantic model (Import) + Streamlit dashboard
```

Both presentation layers are intended to read the same marts, so a number shown in Power BI and
the same number on the web dashboard come from one definition rather than two implementations.

## Data model

*Placeholder.*

To be documented: the entity set (managers, funds, investors, commitments, cash flows, NAV, FX
rates, public index), the star schema, and the declared grain of every fact and mart.

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
