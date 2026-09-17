# Private Markets BI Platform

Fund-level private markets reporting — commitments, capital calls, distributions and NAV — from
generated source data through a warehouse to a Power BI semantic model and a web dashboard.

> **Status: scaffolding.** Phase 0 is complete (repository audit, attribution, project structure).
> The sections below are placeholders and say so explicitly. Nothing here reports a result that has
> not been measured. Phase 8 rewrites this file properly.

## Overview

*Placeholder — Phase 8.*

To be written: the one-line value statement, the live dashboard link, and screenshots. No live link
exists yet because no dashboard has been built.

## Architecture

*Placeholder — Phase 8 adds the Mermaid diagram.*

Intended shape, none of it built yet beyond the scaffolding:

```
generator (seeded, synthetic)
  -> data/raw/*.parquet
  -> Snowflake RAW
  -> dbt: staging -> intermediate -> marts
  -> Power BI semantic model (Import) + Streamlit web dashboard
```

The two presentation layers read the same marts, so a number shown in Power BI and the same number
shown on the web dashboard come from one definition rather than two implementations.

## Data model

*Placeholder — Phases 1 and 2.*

To be documented: the entity set (managers, funds, investors, commitments, cash flows, NAV, FX
rates, public index), the star schema, and the declared grain of every fact and mart.

## Metrics definitions

*Placeholder — Phase 2.*

To be documented as a table of formula, grain, as-of convention and net-vs-gross treatment for:
commitment, paid-in, unfunded, distributions, NAV, DPI, RVPI, TVPI, net IRR and KS-PME.

Two conventions that will be stated explicitly rather than assumed, because both are easy to get
silently wrong: TVPI is computed as a ratio of sums, never an average of ratios; and an IRR that
fails to converge is NULL, never 0.

## Dashboards

*Placeholder — Phases 4 and 6.*

To be built: a Power BI semantic model and report (PBIP/TMDL/PBIR, with RLS for external LP
access), and a Streamlit web dashboard over the same marts so the work is viewable without
installing Power BI Desktop.

## CI/CD

*Placeholder — Phase 5.*

To be built: pull request CI running ruff, pytest, sqlfluff, a deferred dbt build into a
PR-specific Snowflake schema, and Best Practice Analyzer checks against the semantic model. A local
`.pre-commit-config.yaml` already mirrors the lint and formatting half of that gate.

## How to run

*Placeholder — filled in as each phase lands. Working today:*

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[warehouse,app,dev]"
pre-commit install
pytest
```

Credentials, when Snowflake enters the picture in Phase 3, come only from environment variables.

## Design decisions

*Placeholder — Phase 8 adds `docs/adr/` with the full records.*

Two decisions already made and acted on:

- **Business logic lives in dbt, not DAX.** Metrics are computed once in the warehouse and the
  semantic model only aggregates them. The audited predecessor project computed rolling windows
  inside DAX; see `docs/AUDIT.md` for why that is the pattern being avoided.
- **The first commit is the unmodified upstream project.** This makes the diff from that commit an
  exact record of what is original here, rather than something a reader has to take on trust.

## Attribution

This project reuses a small number of engineering patterns from
[C0k11/quantai](https://github.com/C0k11/quantai) (MIT). Four files were adapted and are listed
individually, with every change described, in [ATTRIBUTION.md](ATTRIBUTION.md). The domain layer
shares nothing — that project analyses public equities.

[`docs/AUDIT.md`](docs/AUDIT.md) is the pre-work audit of what the inherited repository actually
contained, with a file path as evidence for every claim.

## License

MIT. See [LICENSE](LICENSE), which carries both the original copyright notice and this project's.
