# LP Lens: Private Markets Fund Performance Analytics Platform

Fund-level private markets reporting — commitments, capital calls, distributions and NAV — from
generated source data through a warehouse to a Power BI semantic model and a web dashboard.

> **Status: In development — Phase 2 warehouse on DuckDB.**
> Generator and dbt marts are built and tested locally. Snowflake load, Power BI and Streamlit
> are not. Nothing below reports a result that has not been measured.

## Overview

*Placeholder.*

To be written: the one-line value statement, the dashboard link and screenshots. No link exists
yet because no dashboard has been built.

## Architecture

```
seeded synthetic generator
  -> data/raw/*.parquet
  -> dbt (DuckDB): staging -> intermediate -> marts
  -> Power BI semantic model (Import) + Streamlit dashboard   # designed, not deployed
```

Snowflake RAW and a Snowflake dbt target are Phase 3; every SQL model uses `adapter.dispatch` so
the same code can compile there, but that target has not been run. Both presentation layers are
still intended to read the same marts, so a number shown in Power BI and the same number on the
web dashboard come from one definition rather than two implementations.

**Phase 3 known gap (designed, not deployed).** `int_returns_by_quarter` and
`int_portfolio_returns_by_quarter` import `lp_lens.metrics.returns`. On DuckDB that import
resolves against the local package. On Snowflake, dbt Python models run in Snowpark, which has
no `lp_lens` on `sys.path` unless the wheel is staged or the solver is inlined. IRR/PME will not
run on a Snowflake target until that packaging step exists. Do not copy the solver into SQL to
work around it — the project rule is one implementation. Tracked in
[#5](https://github.com/tkaushik015/private-markets-bi/issues/5).

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

Star schema over the Phase 1 Parquet, built by dbt on DuckDB. Staging models are views that rename
and cast only. Intermediate models convert currency, build the quarter spine and compute returns.
Marts are tables with enforced contracts. Row counts below are from a DuckDB build against the
seeded generator in `configs/generator.yaml`.

| Mart | Grain | Rows |
|---|---|---|
| `dim_manager` | one row per GP | 25 |
| `dim_fund` | one row per fund | 60 |
| `dim_investor` | one row per LP | 12 |
| `dim_strategy` | one row per strategy | 7 |
| `dim_date` | one row per calendar day, with `is_quarter_end` | 5,295 |
| `fct_cash_flows` | one row per cash flow | 3,078 |
| `fct_nav_quarterly` | fund × investor × quarter end | 4,454 |
| `fct_fund_performance_quarterly` | fund × investor × as-of quarter | 4,454 |
| `fct_portfolio_performance_quarterly` | investor × as-of quarter | 656 |

`fct_fund_performance_quarterly` is a point-in-time series, not a single snapshot:
`is_latest_quarter` marks the current row per position (156 rows at 2026-06-30). Portfolio facts
are aggregated from cash flows and NAV, not from the fund-level fact, so a fund that liquidated
years ago still sits in the investor's inception-to-date totals.

Column-level formula docs live in `warehouse/models/marts/schema.yml` and
`warehouse/models/marts/_metric_definitions.md`.

## Metrics definitions

Every metric is **inception-to-date as at `as_of_quarter`** and **net to the LP of management
fees**. Carried interest is not modelled in the source data, so these figures are not net of
carry. An unknown or uncomputable value is NULL, not 0. IRR is solved once, in
`src/lp_lens/metrics/returns.py`; the dbt Python models import that module rather than
reimplementing it in SQL.

| Metric | Formula | Grain |
|---|---|---|
| Commitment | LP commitment, converted at the FX rate on the commitment date | position / portfolio |
| Paid-in | Capital calls + management fees, each converted at the rate on its flow date | same |
| Unfunded | Commitment + recallable distributions to date − paid-in | same |
| Distributions | Distributions + recallable distributions (USD) | same |
| NAV | Quarter-end residual value, converted at the rate on the quarter-end date | same |
| DPI | `distributions_usd / paid_in_usd` | same |
| RVPI | `nav_usd / paid_in_usd` | same |
| TVPI | `(distributions_usd + nav_usd) / paid_in_usd`, equal to DPI + RVPI | same |
| Net IRR | XIRR of signed LP flows through the quarter, with residual NAV as a terminal positive flow. Actual/365. NULL if there is no sign change or the solver does not converge. | same; portfolio IRR is pooled flows, not an average of fund IRRs |
| KS-PME | Kaplan-Schoar: `(Σ dist_t · I_T/I_t + NAV_T) / Σ contrib_t · I_T/I_t` against the synthetic public index | same |

TVPI is a **ratio of sums, never an average of fund ratios**. Paid-in of zero yields NULL
multiples, not zero. The paid-in cap is enforced in the fund's own currency: on this seed the USD
paid-in/commitment ratio reaches 2.47% over 1.0 for EUR funds (each call converted on its own
date, the commitment on signing), while the local-currency ratio never exceeds 0.9784.

Latest-quarter medians from `fct_fund_performance_quarterly` where `is_latest_quarter`, as-of
**2026-06-30**. These are medians of 156 positions, not AUM-weighted.

| Strategy | Positions | Median TVPI | Median net IRR |
|---|---|---|---|
| Buyout | 60 | 1.435 | 7.80% |
| Growth | 24 | 2.213 | 16.04% |
| Infrastructure | 9 | 1.125 | 1.91% |
| Private Credit | 13 | 1.197 | 5.45% |
| Real Estate | 12 | 1.650 | 10.97% |
| Secondaries | 24 | 1.098 | 3.21% |
| Venture | 14 | 2.042 | 13.26% |
| All positions | 156 | 1.270 | 6.19% |

## Dashboards

*Placeholder.*

To be built: a Power BI semantic model and report (PBIP / TMDL / PBIR), and a Streamlit dashboard
over the same marts so the work is viewable without installing Power BI Desktop. `powerbi/`
currently holds an empty PBIP scaffold only, described in [`powerbi/README.md`](powerbi/README.md).

## CI/CD

`.github/workflows/ci.yml` runs on every pull request and on pushes to `main`. It installs the
`warehouse` and `dev` extras, generates the seeded Parquet, lints SQL with sqlfluff's dbt
templater, runs `dbt build` on DuckDB, then pytest (including a mart reconciliation against an
independent pandas path). Still to be added: a Snowflake dbt target and a deferred build into a
PR-specific schema (Phase 3), and Best Practice Analyzer checks on the semantic model (Phase 4).
`.pre-commit-config.yaml` mirrors the lint half of that gate locally.

## How to run

What works today:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[warehouse,dev]"
pre-commit install

# Generate the synthetic source data into data/raw/ (gitignored).
python -m lp_lens.generate --config configs/generator.yaml --out data/raw

export LP_LENS_RAW_DIR=data/raw
export LP_LENS_DB_PATH=data/warehouse/lp_lens.duckdb
dbt build --project-dir warehouse --profiles-dir warehouse --target local
pytest
```

Snowflake credentials, once that target exists, come only from environment variables. The DuckDB
path above is the default in `warehouse/profiles.yml`. Python models still cannot run on Snowflake
as written; see the Phase 3 known gap under [Architecture](#architecture).

## Design decisions

*Placeholder.*

Two decisions already made and acted on:

- **Business logic lives in dbt, not DAX.** Metrics are computed once in the warehouse
  (`fct_fund_performance_quarterly`, `fct_portfolio_performance_quarterly`), with the semantic
  model only aggregating them. IRR and PME are solved in `src/lp_lens/metrics/returns.py` and
  imported by the dbt Python models; they are not rewritten in SQL or DAX. The audited predecessor
  project computed rolling windows inside DAX; [`docs/AUDIT.md`](docs/AUDIT.md) section 3 records
  why that is the pattern being avoided.
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
