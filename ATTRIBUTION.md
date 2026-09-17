# Attribution

LP Lens began from **[C0k11/quantai](https://github.com/C0k11/quantai)**, a personal quant
workbench released under the **MIT License, Copyright (c) 2025 QuantAI**.

That project's domain is public equities: price history, trading signals, backtests, a multi-agent
LLM analyst and a paper trading engine. LP Lens is a private markets fund performance analytics
platform — funds, commitments, capital calls, distributions and NAV — and shares none of that
domain. What the two share is a handful of engineering patterns, listed exhaustively below.

## Baseline commit

The first commit on `main` is the upstream project, byte for byte, with nothing of mine in it:

```
c68587f3350e0647b25ae5bcd2bb90267a5516e5
chore: import QuantAI (C0k11/quantai, MIT) as unmodified baseline
```

## How to verify this yourself

```bash
git log --reverse --oneline | head -1
# c68587f chore: import QuantAI (C0k11/quantai, MIT) as unmodified baseline

git diff c68587f3350e0647b25ae5bcd2bb90267a5516e5..HEAD --stat
```

That diff is the complete, auditable record of my contribution. Anything it shows as added is
mine; anything it shows as unchanged is the original author's. No claim in this file has to be
taken on trust.

[`docs/AUDIT.md`](docs/AUDIT.md) is the audit of the baseline written before any of it was
changed, with a file path as evidence for every claim. It is the reference for what was inherited
and why each piece was kept or dropped.

## Files retained and adapted

Four files carrying real logic survive from upstream. All four were modified: every Chinese comment
and docstring was translated to English, and the changes below were made. Each file carries an
"Adapted from" header naming its origin.

| File | Upstream path | What changed |
|---|---|---|
| `warehouse/macros/cross_db.sql` | same | Comments translated. Dispatch namespace changed from `quantai_warehouse` to `lp_lens_warehouse`. Three of the five macros dropped — `iso_day_of_week`, `year_month` and `local_date_from_utc` — because private markets data has no trading calendar and no intraday UTC timestamps. `day_spine` and `asof_left_join` kept, both unchanged in logic; the dispatch structure is kept as-is. |
| `warehouse/macros/generate_schema_name.sql` | same | Comment translated and extended to name the `intermediate` layer, which upstream did not have. Logic unchanged. |
| `infra/snowflake/reconcile.py` | same | Docstring and comments translated. Query tag renamed to `lp-lens-reconcile`. Reformatted by ruff. Two behavioural edits: the schema is now a `--schema` argument defaulting to `marts` rather than the hard-coded `marts`, so the script is generic and not tied to a mart set that does not exist yet; and both `zip` calls state `strict=` explicitly (`False` across rows, where a count mismatch is already reported as a problem, and `True` across cells, where the column check makes a length mismatch impossible and therefore a bug). The comparison arithmetic is untouched — the two-layer fingerprint-then-cell design, the exact-integer rule, the 1e-9 relative and 1e-12 absolute float tolerances and the non-zero exit on any difference are all the original author's. |
| `infra/snowflake/sfconn.py` | same | Retained because `reconcile.py` imports it for the connection and the error masking. Docstring and comments translated. Object-name defaults changed from `QUANTAI_*` to `LP_LENS_*`. `mask()` reworked: the S3 bucket and IAM ARN patterns were dropped, because this project has no data lake, and the private key path is masked instead. Reformatted by ruff. |

### Why these four

`asof_left_join` is the non-obvious one. DuckDB and Snowflake both support ASOF joins but place the
time comparison differently — DuckDB takes it in `ON`, Snowflake requires `MATCH_CONDITION` and
permits only equality in `ON`. Converting an irregularly dated cash flow at the most recent FX rate
on or before it needs exactly that join, on both engines. Working this out from scratch would have
cost real time.

`reconcile.py` is retained because its design is better than the obvious one. Comparing column
fingerprints alone would miss a single changed cell in a large column; comparing cells alone gives
no signal about *which* column drifted. Doing both, and treating only the cell comparison as the
verdict, is a deliberate choice worth keeping.

### Three further files are upstream boilerplate, effectively unchanged

Named separately because calling them "adapted" would overstate the work, and leaving them out
would understate what was reused:

- `powerbi/LPLens.SemanticModel/definition.pbism`
- `powerbi/LPLens.SemanticModel/definition/database.tmdl`
- `powerbi/LPLens.SemanticModel/definition/cultures/en-US.tmdl`

Each matches its upstream counterpart exactly apart from a trailing newline. Between them they
declare a format version, a compatibility level and the `en-US` culture; none contains anything
project-specific to change. They carry no "Adapted from" header because neither TMDL nor JSON has
a comment syntax to put one in, so they are recorded here instead. They remain subject to the
original notice. Every other file under `powerbi/` is new.

## Ideas and layouts adapted, with no code carried over

These upstream ideas shape LP Lens, but no lines were copied, the three boilerplate files above
being the only exception. They are listed because the influence is real and should be acknowledged.

| Idea | Upstream source | How it was changed |
|---|---|---|
| **Layered dbt project.** `raw` → `staging` → `marts`, staging as views and marts as tables, materialization set once at directory level in `dbt_project.yml` rather than per model | `warehouse/dbt_project.yml` lines 15-22 | Same layering and the same directory-level materialization, with an **`intermediate/` layer added** that upstream had none of. `warehouse/models/{staging,intermediate,marts}/` in this commit is the empty form of that layout; the models themselves are Phase 2. Upstream's `dbt_project.yml` and `profiles.yml` were deleted rather than edited, because both are named and pathed for the equities project. |
| **Grain uniqueness enforced on every mart**, by a `unique` test or a purpose-written singular test | `warehouse/models/marts/schema.yml` and `warehouse/tests/assert_*_unique_grain.sql` | Same discipline, promoted to a project rule in `.cursor/rules/project.mdc`, and extended with enforced model contracts, which upstream had none of. Upstream's 10 singular tests were deleted; all 10 assert equities facts. |
| **PBIP layout.** Power BI as code: semantic model in plain-text TMDL, whole artifact diffable in git, machine-local cache files git-ignored | `powerbi/QuantAI.pbip`, `powerbi/QuantAI.SemanticModel/definition/**` | Same principle and the same `.pbip` / `.platform` / `definition.pbism` / TMDL skeleton, rebuilt empty as `powerbi/LPLens.SemanticModel` and `powerbi/LPLens.Report` — apart from the three boilerplate files listed above, which had nothing project-specific to rewrite. **The report half changed format:** upstream committed a legacy single-file `report.json` (66 KB, generated by `powerbi/build_report.py`), a choice its README defends as generator-friendly. LP Lens uses **PBIR** instead — a `definition/` folder of per-page and per-visual JSON — so a review diff shows one changed visual rather than one changed 66 KB file. Upstream's entire `powerbi/` contents were deleted: 11 tables, 11 relationships, 48 measures, the six equities report pages, the theme JSON and the hard-coded `D:\` machine paths in `expressions.tmdl`. |
| **The DAX-vs-Python QA page, with wiring canaries.** A hidden report page joining live DAX measure output against expected values computed independently in Python, split into two classes: measure-arithmetic checks and model-wiring checks | `powerbi/verify/verify_dax.py`, `powerbi/verify/expected_values.csv` and the hidden QA page; rationale in `powerbi/README.md` lines 90-95 | **The single best idea inherited, and the reason it is worth crediting loudly:** upstream's author found all 53 arithmetic checks passing green while every date relationship in the model was silently dead, then added the 14 wiring checks specifically to catch that, and ran a negative control — deleting the relationships turned 11 of 11 wiring checks red. LP Lens reimplements the same two-class design against private markets metrics (DPI, RVPI, TVPI, net IRR, KS-PME) rather than Sharpe and rolling volatility, and keeps the negative control as an explicit step. None of upstream's 67 expected values apply. Phase 4 work; nothing of it exists in this commit. |
| **Integration test that seeds a warehouse, invokes `dbtRunner` programmatically, then reconciles SQL output against an independent Python implementation** | `tests/warehouse/test_dbt_build.py` | Same shape, to reconcile dbt-computed IRR, TVPI and DPI against `src/lp_lens/` instead of time-weighted returns. Phase 2 work. |
| **Snowflake raw load as a single transaction with rollback**, refusing to load an incomplete snapshot | `infra/snowflake/load_raw.py` | Same transactional guarantee, to be rewritten for `PUT` to an internal stage instead of an S3 external stage. Upstream's file was deleted, not edited. Phase 3 work. |
| **Cost control**: XSMALL warehouse, `AUTO_SUSPEND = 60`, a resource monitor with a small monthly quota and a suspend trigger | `infra/snowflake/admin_setup.sql` | Same, to be extended to a warehouse per workload and a LOADER / TRANSFORMER / REPORTER role split where upstream had a single role. Upstream's file was deleted, not edited. Phase 3 work. |
| **CI secret hygiene**: OIDC in place of long-lived credentials, account identifiers masked in logs, a fail-closed smoke test asserting an unauthenticated request is rejected | `.github/workflows/deploy.yml` lines 62-69 | Conventions kept, workflow not. Upstream's `deploy.yml` deploys an AWS Lambda stack and has **no `pull_request` trigger at all**, so it reviewed nothing on the way in. It was deleted and replaced by `.github/workflows/ci.yml`, which triggers on `pull_request` and on `push` to `main`. The masking convention already appears in `sfconn.mask()`. |

## Deliberately not carried over

Noted so the omissions read as decisions rather than oversights.

- **Business logic in DAX.** Upstream's `Rolling Vol 20D (Ann)`, `MA 20/50/200` and indexed-series
  measures rebuild 20-trading-row windows inside DAX with `TOPN` and `STDEVX.S`. That work is
  careful and well documented, but it puts business logic in the semantic model. LP Lens computes
  metrics in dbt and keeps DAX thin, so the pattern is rejected on purpose.
- **The entire domain layer.** All 11 sources, all 21 models, all 10 marts, all 48 measures and all
  six visible report pages are public-equities constructs. None apply to funds, commitments, cash
  flows or NAV.
- **Data acquisition.** The `yfinance` price feed, RSS news ingestion and the Polymarket
  integration are gone. Private markets fund-level data is not publicly available, so LP Lens
  generates seeded synthetic data instead — which also removes the live-network dependency that
  made the upstream ETL non-deterministic.
- **The AWS Lambda / SAM deployment stack, the Terraform data lake, and the Streamlit equities
  app.** Out of scope. The Streamlit app talks to upstream's FastAPI service and renders equities
  and LLM views, so Phase 6 is a rewrite rather than an edit.

## License

Upstream is MIT, which permits this reuse provided the copyright notice and the permission notice
are retained. [`LICENSE`](LICENSE) carries the original `Copyright (c) 2025 QuantAI` notice
alongside the notice for work added here. The four adapted files and the three boilerplate files
above remain subject to the original notice.
