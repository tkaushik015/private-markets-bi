# Repository audit — QuantAI, read before extending

Audit date: 2026-09-16. Scope: the repository as checked out at
`/Users/tusharkaushik/Downloads/quantai-main`. No files were modified other than this one.

Purpose: establish what already exists before building a private markets BI platform on top of
it, so that the extension work adds capability rather than duplicating it.

## Finding 0 — this checkout is not a git repository

There is no `.git` directory; `git status` returns
`fatal: not a git repository`. The repo ships `.gitignore`, `.gitattributes` and
`.github/workflows/`, so it was distributed as a source archive rather than a clone.

This blocks the playbook's "commit at the end of every phase, open a PR, merge" instruction until
a repository is initialised and a remote is created. It also means there is no existing commit or
PR history to inherit — the PR history will start from zero.

---

## 1. dbt

Project root `warehouse/`, project name `quantai_warehouse`, profile `quantai`
(`warehouse/dbt_project.yml`). Layout is `raw` (loaded by a pandas ETL, not by dbt) →
`staging` → `marts`.

Materialization is configured **only** at the directory level in
`warehouse/dbt_project.yml` lines 15-22: `staging: +materialized: view`,
`marts: +materialized: table`. A `grep` for `{{ config(` across `warehouse/models/` returns
nothing, so no model overrides its materialization. There are no incremental models anywhere.

### Staging models — 11, all views, zero model-level tests

`stg_backtest_equity`, `stg_backtest_runs`, `stg_event_odds`, `stg_news`, `stg_news_scores`,
`stg_portfolio_cash`, `stg_positions`, `stg_prices`, `stg_signals`, `stg_trades`,
`stg_trading_days` (all in `warehouse/models/staging/`).

There is no `schema.yml` in `warehouse/models/staging/` — only `_sources.yml`. The staging layer
is therefore entirely undocumented and untested at the model level; the 26 tests in that file are
attached to the **sources**, not the staging models.

### Mart models — 10, all tables

| Model | Materialization | Tests declared in `models/marts/schema.yml` | Grain uniqueness enforced by |
|---|---|---|---|
| `dim_date` | table | `date` not_null + unique; `day_of_week` accepted_values | schema.yml `unique` |
| `dim_symbol` | table | `symbol` not_null + unique | schema.yml `unique` |
| `fact_prices` | table | `symbol` not_null + relationships→`dim_symbol`; `date` not_null + relationships→`dim_date`; `close` not_null | `tests/assert_fact_prices_unique_grain.sql` |
| `fact_positions` | table | `symbol` not_null + relationships; `shares` not_null | `tests/assert_fact_positions_unique_grain.sql` |
| `fact_trades` | table | `action` accepted_values; `symbol` relationships | `tests/assert_fact_trades_unique_grain.sql` |
| `fact_signals` | table | `symbol` not_null + relationships; `date` not_null + relationships; `composite_signal` not_null; `signal_strength` accepted_values | `tests/assert_fact_signals_unique_grain.sql` |
| `fact_backtest_results` | table | `run_id` not_null + unique | schema.yml `unique` |
| `fact_backtest_equity` | table | `run_id` not_null + relationships→`fact_backtest_results`; `equity` not_null | `tests/assert_fact_backtest_equity_unique_grain.sql` |
| `fact_news` | table | `link` not_null + unique; `title` not_null; `sentiment_label` accepted_values | schema.yml `unique` |
| `fact_event_odds` | table | `market_id` not_null; `yes_price` not_null | `tests/assert_fact_event_odds_unique_grain.sql` |

**This is the single strongest thing in the repo and should be carried forward:** all ten marts
have their grain uniqueness enforced, either by a `unique` test or by a purpose-written singular
test. That discipline is exactly what the playbook's "every new mart needs a declared grain" rule
asks for, and it is already habitual here.

### Singular tests — 10

In `warehouse/tests/`: six `assert_fact_*_unique_grain.sql`, plus
`assert_backtest_drawdown_nonpositive.sql`, `assert_positions_pnl_consistent.sql`,
`assert_prices_ohlc_sane.sql`, and `warn_positions_without_price.sql` (the only one whose name
implies a `warn` severity).

### Test count reconciles

32 generic tests on marts + 26 source tests + 10 singular tests = **68**, which matches the
`21 models and 68 tests` figure the README reports at line 580 for the Snowflake build. Model
count also reconciles: 11 staging + 10 marts = 21.

### Absent entirely

Verified by `rg -n "freshness|contract|exposure|metrics|semantic_model|snapshot|versions" warehouse/`,
which returns only two incidental matches (Chinese prose comments mentioning the Python module
`quantai/backtest/metrics.py`).

| Feature | Status |
|---|---|
| Model contracts (`contract: enforced`) | Not present |
| Exposures | Not present — no `exposures.yml` anywhere |
| Snapshots (SCD2) | Not present — no `snapshots/` directory |
| Source freshness (`freshness:` / `loaded_at_field`) | Not present in `_sources.yml` |
| Semantic layer / MetricFlow metrics | Not present |
| `packages.yml` / `dbt_utils` | Not present — the project has zero package dependencies |
| `seeds/` | Not present |
| `analyses/` | Not present |
| Intermediate layer | Not present — staging feeds marts directly |
| Column-level descriptions | Not present — descriptions exist only at model level, and are written in Chinese |

### Macros — worth reusing

`warehouse/macros/cross_db.sql` implements five `adapter.dispatch` macros with `default__`
(DuckDB) and `snowflake__` variants: `day_spine`, `year_month`, `iso_day_of_week`,
`local_date_from_utc`, `asof_left_join`. `warehouse/macros/generate_schema_name.sql` overrides
dbt's default schema concatenation so `+schema: marts` lands in a schema literally named `marts`
instead of `main_marts`.

Both are directly reusable for the private markets project. The `asof_left_join` macro in
particular (DuckDB `ASOF LEFT JOIN` vs Snowflake `ASOF JOIN ... MATCH_CONDITION`) is the
non-obvious one, and a quarter-end NAV lookup needs exactly that shape.

---

## 2. Snowflake

**The default dbt target is DuckDB, not Snowflake.** `warehouse/profiles.yml` line 10 reads
`target: local`, and the `local` output is `type: duckdb` pointing at
`../data/warehouse/quantai.duckdb` (overridable via `QUANTAI_DB_PATH`). The `snowflake` output
exists at lines 16-27 but must be selected explicitly with `--target snowflake`. There is no
`dev`/`ci`/`prod` target separation — one DuckDB target and one Snowflake target, total.

Credential handling is already correct and should be kept: account, private key path, role,
warehouse, database and schema all come from `env_var()`, with key-pair auth and no passwords.
Nothing account-specific is committed.

**Power BI does not connect to Snowflake.** It connects to CSV files only — see section 3.

Supporting Snowflake assets:

- `infra/snowflake/admin_setup.sql` — applied by hand as `ACCOUNTADMIN`. Creates warehouse
  `QUANTAI_WH` (XSMALL, `AUTO_SUSPEND = 60`), resource monitor `QUANTAI_RM` (20 credits/month,
  notify at 80%, suspend at 100%), database `QUANTAI`, a single role `QUANTAI_DBT`, a key-pair
  service user, and storage integration `QUANTAI_S3_RAW`. Note: **one role, not three** — there
  is no LOADER/TRANSFORMER/REPORTER split, and no `REPORTER`-style read-only grant on marts.
- `infra/snowflake/load_raw.py` — loads Parquet from S3 into `RAW` via an **external** stage
  (storage integration over `s3://<bucket>/raw/`), `DELETE` + `COPY INTO` for 9 tables inside a
  single transaction with rollback on failure. Refuses to load if any table's file is missing or
  if file write times span more than 10 minutes, so a half-written snapshot cannot land. It does
  **not** use `PUT` to an internal stage; the path is S3 → external stage → Snowflake.
- `infra/snowflake/reconcile.py` — compares DuckDB marts against Snowflake marts cell by cell:
  column fingerprints first, then row-aligned cell comparison with exact integer equality and
  `rel_tol=1e-9` / `abs_tol=1e-12` for floats. Exits 1 on any difference. This is a strong,
  directly reusable pattern.
- `infra/terraform/snowflake.tf` — the read-only IAM role Snowflake assumes for the `raw/` prefix.

Per README lines 579-586, Snowflake builds are run **manually and on demand**, not scheduled and
not wired into CI. Reported: 9 tables / 36,014 rows loaded, 89 dbt nodes passing in 8.2–8.7 s,
0.08 credits consumed across all runs to date.

---

## 3. Power BI

### Format — mixed, and the report half is the legacy format

- `powerbi/QuantAI.pbip` — PBIP project entry, `version: 1.0`.
- `powerbi/QuantAI.SemanticModel/definition/**` — **TMDL**, hand-written, plain text.
- `powerbi/QuantAI.Report/definition.pbir` — `version: 4.0`, `datasetReference.byPath`.
- `powerbi/QuantAI.Report/report.json` — **legacy single-file `report.json`, 66 KB**, generated
  by `powerbi/build_report.py`. This is *not* PBIR folder format. `powerbi/README.md` line 211
  confirms the choice was deliberate: "Report layout uses the classic `report.json` format
  (stable, text, generator-friendly) rather than the PBIR preview format."

So: semantic model is modern TMDL, report is legacy JSON. The playbook's Phase 4.2 asks for PBIR,
which is a genuine format change, not a port.

### Tables — 11, every one of them backed by a CSV file

10 data tables (`dim_date`, `dim_symbol`, `fact_prices`, `fact_signals`, `fact_positions`,
`fact_backtest_equity`, `fact_backtest_results`, `fact_news`, `fact_event_odds`, `qa_expected`)
plus a measures-only table `_Measures`.

Every partition is `mode: import` with `Source = Csv.Document(File.Contents(...))` — confirmed
across all 10 data tables. Example, `tables/fact_prices.tmdl` lines 102-110. Nine read from the
`ExportFolder` parameter, `qa_expected` reads from `VerifyFolder`. Both parameters are defined in
`definition/expressions.tmdl` and **still carry the original author's hard-coded machine paths**
(`D:\Project\Stock\data\exports`, `D:\Project\Stock\powerbi\verify`). There is no Snowflake
connector, no `Snowflake.Databases(...)`, and no server/warehouse/database parameter.

### Relationships — 11, four of them auto-detected

`definition/relationships.tmdl`. Seven are hand-named (`date_to_signals`, `symbol_to_news`, etc.);
four carry `AutoDetected_<guid>` names, meaning Power BI Desktop created them rather than the
author. No `crossFilteringBehavior` is declared on any relationship, so all are single-direction
by default — which is what you want, but it is implicit rather than asserted.

`dim_date` is **not marked as a date table**: `tables/dim_date.tmdl` contains no
`dataCategory: Time` and no `isDateTable` marking.

### Measures — 48, none documented

All 48 live in `tables/_Measures.tmdl`. Every one carries a `displayFolder`
(Windowed, Prices, Risk, Positions, Signals, Backtest, News & Events), which is good practice
already in place. But `grep -c "^\t///" _Measures.tmdl` returns **0** — not a single measure has a
description. The playbook's requirement that descriptions copy the dbt doc definitions has no
existing foundation to build on.

Several measures push real computation into DAX rather than reading a precomputed column:
`Rolling Vol 20D (Ann)`, `MA 20/50/200`, `SPY Indexed 100`, `Equity Indexed 100` rebuild
20-trading-row windows with `TOPN` and `STDEVX.S`. `powerbi/README.md` lines 40-62 documents why
in detail. This is the opposite of the "logic lives in dbt, not DAX" rule the new project adopts,
and is the clearest example of a pattern to deliberately *not* carry over.

### Absent entirely

Verified by grep across `powerbi/QuantAI.SemanticModel/definition/`:

| Feature | Status |
|---|---|
| RLS roles / `USERPRINCIPALNAME()` | **Not present** — zero roles, zero row filters |
| Calculation groups | **Not present** |
| Field parameters | **Not present** |
| Measure descriptions | **Not present** (0 of 48) |
| `dim_date` marked as date table | **Not present** |
| Best Practice Analyzer / `bpa-rules.json` | **Not present** |
| Tabular Editor CLI usage | **Not present** |
| TMDL linting of any kind | **Not present** |

### What is genuinely strong here

`powerbi/verify/verify_dax.py` → `powerbi/verify/expected_values.csv` produces 67 expected values
from the same CSVs, which a hidden QA page joins against live DAX measures at relative tolerance
1e-6. It is split into two classes: 53 measure-arithmetic checks and 14 model-wiring checks, the
latter existing specifically because — as `powerbi/README.md` lines 90-95 records — all 53
arithmetic checks passed green while every date relationship in the model was silently broken.
The author also ran a negative control: deleting the relationships turned 11 of 11 wiring checks
red.

That "relationship canary" idea is the single most transferable piece of the Power BI work and
the playbook is right to ask for it again in Phase 4.2.

Documented limitation, `powerbi/README.md` lines 191-195: free Desktop only, no Power BI Service
workspace, so the deliverable is the PBIP plus screenshots. Seven screenshots exist in
`powerbi/img/`.

---

## 4. CI

**There is exactly one workflow: `.github/workflows/deploy.yml`.**

| Property | Value |
|---|---|
| Triggers | `push` to `main` (path-filtered) and `workflow_dispatch` |
| **Runs on pull requests** | **No** — there is no `pull_request` trigger anywhere in the repo |
| Jobs | `test` → `deploy` |
| `test` job | `pip install -e ".[ui,warehouse,serve,dev]"` then `python -m pytest`. That is the whole job. |
| `deploy` job | AWS OIDC role assumption (no long-lived keys), `sam build`, `sam deploy` to CloudFormation stack `quantai-etl`, API warm-up, smoke test asserting an unauthenticated call returns 401, a `/health` readiness poll, then pinning the deployed image digest in ECR |

What CI does **not** do:

- No `dbt build` step. dbt runs only *indirectly*, inside pytest: `tests/warehouse/test_dbt_build.py`
  seeds a temp DuckDB file and invokes `dbtRunner().invoke(["build", ...])` against the `local`
  target. So dbt is exercised on DuckDB only, never on Snowflake, and never with `--defer` or
  `state:modified+`.
- No `sqlfluff`. Not installed, not configured, not run — `rg -i sqlfluff` across the repo returns
  nothing, and there is no `.sqlfluff` file.
- No Power BI checks of any kind. No BPA, no TMDL validation, no PBIR schema validation.
- No `ruff` step, despite `ruff` being declared in the `dev` extra and configured in
  `pyproject.toml` lines 90-92.
- No `mypy` step, despite being declared and configured.
- No pre-commit. There is no `.pre-commit-config.yaml`.
- No PR template, no `CODEOWNERS`, no `docs/CONTRIBUTING.md`.
- No artifact upload of `manifest.json`, so deferred/slim CI has no state to defer against.

The deploy pipeline is well-built for what it is — OIDC with no static credentials, output masking
for account IDs and API IDs, fail-closed auth smoke test, idempotent image pinning. The security
posture is worth copying. But it gates *deployment*, and reviews nothing about the data or the
semantic model on the way in.

---

## 5. Documentation

- **dbt docs: not published anywhere.** No `dbt docs generate` or `dbt docs serve` invocation in
  any script, workflow, or README. No GitHub Pages workflow. No `target/` artifacts committed.
- **Data dictionary: none.** The closest thing is `warehouse/models/marts/schema.yml`, which has a
  one-line `description:` per mart — **written in Chinese**, with no column-level descriptions and
  no metric formulas.
- `docs/` contains only three PNGs (`icon.png`, `frontend_portfolio.png`, `frontend_workstation.png`).
  No `.md` files at all before this audit.
- `README.md` is 38 KB / ~640 lines, in English, and thorough — but it sells a quant trading and
  LLM system. Its headings are "Multi-agent decision chain", "Teacher-student distillation &
  evolution flywheel", "Paper trading". The data-stack material is real but buried at line 254 and
  line 519.
- `powerbi/SPEC.md` and `powerbi/README.md` are both strong, honest documents — `powerbi/README.md`
  in particular documents seven DAX bugs it caught and root-causes a relationship failure. That
  candour is a good model for the new project's docs.
- Source-code comments throughout `warehouse/`, `infra/snowflake/` and `scripts/` are in Chinese.
  Anything copied into an English-facing portfolio project needs its comments translated, not just
  moved.
- `LICENSE` is MIT, `Copyright (c) 2025 QuantAI`. That exact notice must be preserved in the new
  repo's `LICENSE` and `ATTRIBUTION.md` for any adapted code.

---

## 6. What is public-equities-specific and must be replaced

Effectively the entire data domain. Nothing in the warehouse survives contact with private markets.

**Raw / source layer** (`warehouse/models/staging/_sources.yml`) — all 11 sources are equities
concepts: `prices` (OHLCV), `trading_days` (NYSE calendar), `positions`, `portfolio_cash`,
`trades`, `signals`, `backtest_runs`, `backtest_equity`, `news`, `news_scores`, `event_odds`
(Polymarket prediction-market prices).

**The grain itself is wrong.** Every fact is keyed on `symbol × date` — a dense daily series on a
ticker. Private markets facts are `fund_id × investor_id × irregular transaction date` for cash
flows and `fund_id × investor_id × quarter_end` for NAV. Sparse, irregular, and two-dimensional on
the entity side. `dim_symbol` has no analogue; it becomes `dim_fund` + `dim_manager` +
`dim_investor` + `dim_strategy`.

**`dim_date` must change shape.** It is currently a calendar-day spine with an `is_trading_day`
flag for NYSE. Private markets need quarter-end flags and a quarter spine; trading days are
meaningless.

**Metrics have no overlap.** Existing: Sharpe, CAGR, max drawdown, win rate, annualized
volatility, moving averages, composite signal strength. Needed: DPI, RVPI, TVPI, net IRR (XIRR
over irregular dates), KS-PME, paid-in, unfunded, called percentage. Not one carries over. In
particular there is **no XIRR or IRR implementation anywhere in the repo** — `quantai/backtest/metrics.py`
computes time-weighted returns on a dense series, which is the wrong tool for irregular cash flows.

**Entities that simply do not exist:** managers/GPs, funds, vintages, strategies, commitments,
capital calls, distributions, management fees, recallable distributions, NAV, FX rates,
multi-currency amounts, a public index for PME.

**Data acquisition must be replaced wholesale.** `yfinance`, `feedparser` RSS news, and the
Polymarket integration all go. Private markets fund-level data is not publicly available, so the
new project needs a seeded synthetic generator — which also removes the live-network dependency
that currently makes this repo's ETL non-deterministic.

**Power BI artifacts are equities-shaped end to end:** all 10 tables, all 11 relationships, all 48
measures, all six visible report pages (Market Overview, Signals, Backtest vs Benchmark, Risk &
Volatility, News & Event Odds) and all 67 QA checks. Only the *structure* — TMDL as source of
truth, generated layout, hidden QA page reconciled against Python — survives.

**Not domain-specific, and reusable as-is:** the dispatch macros, the `generate_schema_name`
override, `reconcile.py`, the OIDC/secret-masking patterns in `deploy.yml`, the resource-monitor
cost cap, and the `pytest` → `dbtRunner` integration-test harness.

---

## Capability summary

| Capability | Present | Evidence |
|---|---|---|
| Git repository / commit history | **no** | no `.git` directory; `git status` fails |
| dbt project, layered raw→staging→marts | **yes** | `warehouse/dbt_project.yml` lines 15-22; 11 staging + 10 mart models |
| Mart grain uniqueness tested | **yes** | all 10 marts; 6 singular `assert_*_unique_grain.sql` + 4 `unique` in `schema.yml` |
| dbt tests overall | **yes** (68) | 32 marts generic + 26 source + 10 singular; README line 580 |
| Staging-layer tests/docs | **no** | no `schema.yml` in `warehouse/models/staging/` |
| Column-level descriptions | **no** | `models/marts/schema.yml` has model-level `description` only, in Chinese |
| Model contracts | **no** | no `contract:` key in `warehouse/` |
| Incremental models | **no** | no `{{ config(` in any model |
| Snapshots (SCD2) | **no** | no `snapshots/` directory |
| Source freshness | **no** | no `freshness:` in `_sources.yml` |
| Exposures | **no** | no `exposures.yml` |
| Semantic layer / metrics | **no** | no `semantic_model`/`metrics` keys |
| dbt packages (`dbt_utils`) | **no** | no `packages.yml` |
| Seeds | **no** | no `seeds/` directory |
| Cross-database dispatch macros | **yes** | `warehouse/macros/cross_db.sql`, 5 macros × DuckDB/Snowflake |
| Snowflake account setup as code | **partial** | `infra/snowflake/admin_setup.sql` — 1 role, not LOADER/TRANSFORMER/REPORTER; applied by hand |
| Snowflake raw load | **yes** | `infra/snowflake/load_raw.py` — external S3 stage, transactional `DELETE`+`COPY INTO`, snapshot integrity guard |
| Snowflake as default dbt target | **no** | `warehouse/profiles.yml` line 10: `target: local` (DuckDB) |
| dev/ci/prod target separation | **no** | only `local` and `snowflake` outputs exist |
| DuckDB↔Snowflake reconciliation | **yes** | `infra/snowflake/reconcile.py`, cell-by-cell, `rel_tol=1e-9` |
| Power BI as code | **partial** | semantic model is TMDL; report is legacy `report.json`, not PBIR |
| Power BI source = Snowflake | **no** | every partition is `Csv.Document(File.Contents(...))` reading `ExportFolder` |
| Power BI parameterised connection | **partial** | `ExportFolder`/`VerifyFolder` params exist but hold hard-coded `D:\Project\Stock\...` paths |
| Star schema, single-direction relationships | **partial** | 11 relationships, but 4 are `AutoDetected_*` and direction is implicit |
| `dim_date` marked as date table | **no** | no `dataCategory: Time` in `tables/dim_date.tmdl` |
| DAX measures | **yes** (48) | `tables/_Measures.tmdl` |
| Measure descriptions | **no** (0 of 48) | `grep -c "^\t///" _Measures.tmdl` = 0 |
| Measure display folders | **yes** | all 48 carry `displayFolder` |
| Business logic kept out of DAX | **no** | `Rolling Vol 20D`, `MA 20/50/200`, indexed series all computed in DAX |
| RLS roles | **no** | no `role` object in the TMDL model |
| Calculation groups | **no** | no `calculationGroup` in the TMDL model |
| Field parameters | **no** | no parameter table in the TMDL model |
| Best Practice Analyzer / TMDL lint | **no** | no `bpa-rules.json`, no Tabular Editor reference anywhere |
| DAX-vs-Python QA reconciliation | **yes** | `powerbi/verify/verify_dax.py`, 67 checks, hidden QA page, negative control run |
| Relationship canary tests | **yes** | 14 Class-2 wiring checks; `powerbi/README.md` lines 90-95 |
| CI on pull requests | **no** | `.github/workflows/deploy.yml` triggers on `push: main` + `workflow_dispatch` only |
| CI runs pytest | **yes** | `deploy.yml` `test` job, `python -m pytest` |
| CI runs `dbt build` | **partial** | only indirectly, via `tests/warehouse/test_dbt_build.py` on DuckDB |
| CI runs dbt slim/deferred build | **no** | no manifest artifact is ever uploaded |
| CI runs sqlfluff | **no** | sqlfluff not installed, configured, or referenced |
| CI runs ruff / mypy | **no** | both configured in `pyproject.toml`, neither invoked by any workflow |
| CI runs Power BI checks | **no** | nothing in `deploy.yml` touches `powerbi/` |
| Deploy pipeline with OIDC, no static keys | **yes** | `deploy.yml` lines 62-69 |
| pre-commit | **no** | no `.pre-commit-config.yaml` |
| PR template / CODEOWNERS / CONTRIBUTING | **no** | `.github/` contains only `workflows/deploy.yml` |
| dbt docs published | **no** | no `dbt docs` invocation, no Pages workflow |
| Data dictionary | **no** | model-level Chinese descriptions only |
| Web dashboard | **partial** | `quantai/ui/` Streamlit app exists, but it is equities/LLM and reads the API, not the marts |
| Private markets domain data | **no** | all 11 sources are equities; no fund/commitment/cash-flow/NAV entity exists |
| IRR / XIRR / PME implementation | **no** | `quantai/backtest/metrics.py` is time-weighted on a dense series |

---

## Consequences for the build plan

1. **Initialise a git repository first.** Phase 0.2 cannot produce the PR history the playbook
   depends on until this happens.
2. **Phase 1 is genuinely greenfield.** Nothing in the domain layer is salvageable, so there is no
   duplication risk in writing the generator from scratch.
3. **Phase 2 is mostly new too**, with two real carry-overs: `macros/cross_db.sql` and the
   `pytest` → `dbtRunner` harness in `tests/warehouse/test_dbt_build.py`. Contracts, snapshots,
   freshness, exposures, incremental models, seeds and `dbt_utils` are all net-new — the audit
   found no partial implementations to extend.
4. **Phase 3's reconcile script already exists** and is good; `load_raw.py` needs reworking from
   an S3 external stage to a local `PUT` + `COPY INTO` internal stage, and `admin_setup.sql` needs
   the one-role model split into three.
5. **Phase 4 has no RLS, no calculation group and no field parameter to build on** — all three are
   from zero. The QA-page and relationship-canary patterns are the real inheritance. Note that
   moving to PBIR means `build_report.py` is a rewrite, not an edit.
6. **Phase 5 is the largest true gap.** There is no `pull_request` trigger anywhere, so PR CI is
   built from nothing; but `deploy.yml`'s secret-handling and masking conventions are worth
   copying verbatim.
7. **Phase 6's Streamlit app cannot be adapted** — `quantai/ui/` talks to the FastAPI service and
   renders equities/LLM views. Reuse the theming approach (`quantai/ui/theme.py` and
   `.streamlit/config.toml` share design tokens with the Power BI theme JSON) and write the rest.
8. **Phase 8's README rewrite starts from an English 640-line document about a different product.**
   Treat it as a new document, and translate any Chinese comments that travel with adapted code.
