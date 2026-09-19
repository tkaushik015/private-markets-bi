# LP Lens: Private Markets Fund Performance Analytics Platform

Fund-level private markets reporting — commitments, capital calls, distributions and NAV — from
generated source data through a warehouse to a Power BI semantic model and a web dashboard.

> **Status: In development — Streamlit reads the committed DuckDB marts; Snowflake
> not run; Power BI not built.**
> Generator, dbt marts and the Streamlit query layer are tested on DuckDB. The
> dashboard ships a marts-only synthetic warehouse so a public deploy does not
> need Snowflake. Snowflake setup, load and targets are in the repo; they have
> not been applied to a real account from this work. Power BI is still designed,
> not deployed. Nothing below reports a result that has not been measured.

## Overview

*Placeholder.*

Streamlit is built and runs locally against `app/data/demo.duckdb`. There is no public
Community Cloud URL to report yet — the deploy steps are below, the app has not been
published from this work. No screenshot is included; none has been captured.

## Architecture

```
seeded synthetic generator
  -> data/raw/*.parquet
  -> DuckDB (CI / local)  OR  Snowflake RAW via PUT + COPY
  -> dbt: staging -> intermediate -> marts
  -> Streamlit dashboard over fct_*_performance_quarterly     # built; DuckDB default
  -> Power BI semantic model (Import)                         # designed, not deployed
```

Every SQL dialect difference goes through `adapter.dispatch`. DuckDB is the default target and
the only one CI runs. Snowflake targets (`snowflake_dev`, `snowflake_ci`, `snowflake_prod`)
read the same models; they have not been run against a real account in this work.

**Issue #5 (Snowpark import) — resolved in code, not yet run on Snowflake.** The Python
models import `lp_lens.metrics.returns` after `dbt.config(imports=[wheel])`. The wheel is a
slim packaging of that same file (`infra/snowflake/build_metrics_wheel.py`), staged to
`RAW.LP_LENS_PACKAGES`. The solver is not copied into SQL. A byte-identity test asserts the
wheel contains `src/lp_lens/metrics/returns.py` unchanged. End-to-end Snowpark execution is
**designed, not deployed**.

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

**Streamlit is built. Power BI is designed, not deployed.** `powerbi/` still holds only the
empty PBIP scaffold described in [`powerbi/README.md`](powerbi/README.md).

The web app lives in `app/` and reads **only** `fct_fund_performance_quarterly` and
`fct_portfolio_performance_quarterly` (plus the dimension tables for labels). It does not
recompute IRR, TVPI, DPI, RVPI or PME. `src/lp_lens/query/` is the SELECT-only layer both
the pages and the tests use.

| Sidebar page | File | What it shows |
|---|---|---|
| Portfolio overview | `app/streamlit_app.py` | One LP's latest portfolio-mart row: commitment, paid-in, unfunded, NAV, TVPI, DPI, net IRR. |
| Vintage and strategy | `app/pages/1_Vintage_and_Strategy.py` | Latest fund-mart points. Ratios are not averaged into a vintage or strategy TVPI. |
| J-curve | `app/pages/2_J_Curve.py` | One position's fund-mart `tvpi` / `dpi` / `rvpi` against `fund_age_years`. |
| Fund explorer | `app/pages/3_Fund_Explorer.py` | Latest fund-mart table and that position's quarterly mart history. |
| Metric definitions | `app/pages/4_Metric_Definitions.py` | `{% docs %}` blocks from `warehouse/models/marts/_metric_definitions.md`. |

Every page shows the mart as-of date and a note that young funds sit below 1.0x TVPI because
of the J-curve (fees are paid in before residual value has accrued). The footer prints the
active source, `manifest.json` `generated_at` (or the stamp in `app/data/build_info.json`)
and the git SHA.

**Data source.** Default is the committed file `app/data/demo.duckdb` (marts only, rebuilt
with `python app/export_demo_warehouse.py` after a local `dbt build`). Set
`LP_LENS_APP_SOURCE=snowflake` to read the same mart names from Snowflake. The app then
uses `infra/snowflake/sfconn.py` (key-pair, reporter role by default). Credentials stay in
the environment; a public Community Cloud deploy should keep the DuckDB default.

### Streamlit Community Cloud

The app has not been published from this work. To publish it:

1. Push this branch (or `main` once merged) to GitHub. The repo must include
   `app/data/demo.duckdb` — that is the warehouse the public app reads.
2. At [share.streamlit.io](https://share.streamlit.io), **New app**, pick the repo and
   branch.
3. Advanced settings:
   - **Main file path:** `app/streamlit_app.py`
   - **Requirements file:** `app/requirements.txt` (the repo-root
     `requirements.txt` is the same list, for the default lookup)
   - **Python version:** 3.12
4. Leave secrets empty for the synthetic DuckDB default. Do not paste a Snowflake
   account or key into a public app.
5. Deploy. The first run installs the thin `app/requirements.txt` set (Streamlit,
   Plotly, pandas, DuckDB). It does not install dbt or the Snowflake connector.

`app/_bootstrap.py` puts `src/` on `sys.path` so Community Cloud can import
`lp_lens.query` without an editable install. The footer SHA comes from `GITHUB_SHA`
when that is set, otherwise `git rev-parse`.

## CI/CD

`.github/workflows/ci.yml` runs on every pull request and on pushes to `main`. It installs the
`warehouse` and `dev` extras, generates the seeded Parquet, lints SQL with sqlfluff's dbt
templater, runs `dbt build` on DuckDB, then pytest. CI does **not** connect to Snowflake.
The `snowflake_ci` profile and `CI_<id>_*` schema prefix are designed for a later deferred
build; they are not wired into GitHub Actions yet. Best Practice Analyzer checks on the
semantic model remain Phase 4. Pytest includes the Streamlit query-layer tests, which read
the committed `app/data/demo.duckdb` and do not import Streamlit. `.pre-commit-config.yaml`
mirrors the lint half of that gate locally.

## How to run

What works today:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[warehouse,app,dev]"
pre-commit install

# Generate the synthetic source data into data/raw/ (gitignored).
python -m lp_lens.generate --config configs/generator.yaml --out data/raw

export LP_LENS_RAW_DIR=data/raw
export LP_LENS_DB_PATH=data/warehouse/lp_lens.duckdb
dbt build --project-dir warehouse --profiles-dir warehouse --target local
pytest

# Dashboard. Default source is app/data/demo.duckdb (no dbt required to view).
streamlit run app/streamlit_app.py
```

To refresh the committed demo after a warehouse change:

```bash
python app/export_demo_warehouse.py
```

To point the app at Snowflake (after Phase 3 has actually been run — it has not):

```bash
export LP_LENS_APP_SOURCE=snowflake
# sfconn defaults to LP_LENS_REPORTER / LP_LENS_DEV; set SNOWFLAKE_ACCOUNT
# and SNOWFLAKE_PRIVATE_KEY_PATH. Optional: copy .env.snowflake.example and
# switch the user/role to the reporter.
streamlit run app/streamlit_app.py
```

## Snowflake

**Designed, not deployed.** `infra/snowflake/setup.sql` has not been applied to a real
account from this work, and no load, dbt build or cell-by-cell reconcile has been run
against Snowflake. Figures below that come from DuckDB are labelled as such.

### Architecture

- `LP_LENS_DEV` / `LP_LENS_PROD` with schemas `RAW`, `STAGING`, `INTERMEDIATE`, `MARTS`.
- Roles: `LP_LENS_LOADER` (write RAW), `LP_LENS_TRANSFORMER` (read RAW, write the rest),
  `LP_LENS_REPORTER` (SELECT on MARTS only).
- One X-Small warehouse, `AUTO_SUSPEND = 60`, resource monitor `LP_LENS_RM` at 20 credits
  per month, notify at 80%, suspend at 100%.
- CI schema pattern: target `snowflake_ci` plus `LP_LENS_CI_SCHEMA=CI_PR_<n>` produces
  `CI_PR_<n>_STAGING` / `_INTERMEDIATE` / `_MARTS`. Pair with
  `load_raw.py --raw-schema CI_PR_<n>_RAW`.

### How to run (after setup.sql has been applied as ACCOUNTADMIN)

```bash
cp .env.snowflake.example .env.snowflake.local   # fill account, user, key path
python infra/snowflake/load_raw.py --raw-dir data/raw --env-file .env.snowflake.local --stage-wheel
export LP_LENS_SNOWPARK_WHEEL=@LP_LENS_DEV.RAW.LP_LENS_PACKAGES/lp_lens-0.1.0-py3-none-any.whl
dbt build --project-dir warehouse --profiles-dir warehouse --target snowflake_dev
python infra/snowflake/reconcile.py --duckdb data/warehouse/lp_lens.duckdb --schema marts --env-file .env.snowflake.local
```

Credentials are environment variables only, key-pair auth. The example env file commits
no account identifier. `sfconn.mask` strips the account and key path from any error that
reaches stdout.

The DuckDB-only negative control (no Snowflake) is:

```bash
python infra/snowflake/reconcile.py --negative-control --duckdb data/warehouse/lp_lens.duckdb
```

### Cost guardrails

One warehouse. Sixty-second auto-suspend. Twenty-credit monthly quota that suspends the
warehouse at 100%. PUBLIC loses trial learning-warehouse and Cortex grants so those cannot
bill outside the monitor. Credits used have not been measured: the account was not run.

### Snowpark wheel

`infra/snowflake/build_metrics_wheel.py` packages `src/lp_lens/metrics/returns.py` and
nothing else (`--no-deps`, no duckdb/pydantic). `load_raw.py --stage-wheel` PUTs it to
`RAW.LP_LENS_PACKAGES`. The Python models lazy-import that module after registering the
wheel. Do not inline Newton/Brent into SQL.

## Design decisions

*Placeholder.*

Two decisions already made and acted on:

- **Business logic lives in dbt, not DAX and not Streamlit.** Metrics are computed once in the
  warehouse (`fct_fund_performance_quarterly`, `fct_portfolio_performance_quarterly`). The
  semantic model only aggregates them; the Streamlit app only selects them. IRR and PME are
  solved in `src/lp_lens/metrics/returns.py` and imported by the dbt Python models; they are
  not rewritten in SQL, DAX or the app. The audited predecessor project computed rolling
  windows inside DAX; [`docs/AUDIT.md`](docs/AUDIT.md) section 3 records why that is the
  pattern being avoided.
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
