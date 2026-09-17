# Attribution

This project began from **[C0k11/quantai](https://github.com/C0k11/quantai)**, a personal quant
workbench released under the MIT License, Copyright (c) 2025 QuantAI. That project's domain is
public equities: price history, trading signals, backtests, a multi-agent LLM analyst and a paper
trading engine. This project is a private markets BI platform — funds, commitments, capital calls,
distributions and NAV — and shares none of that domain.

What it does share is a handful of engineering patterns, listed exhaustively below.

## How to verify this yourself

The first commit on `main` is the upstream project, byte for byte, with nothing of mine in it:

```bash
git log --reverse --oneline | head -1
# c68587f chore: import QuantAI (C0k11/quantai, MIT) as unmodified baseline

git diff c68587f..HEAD --stat
```

That diff is the complete, auditable record of my contribution. Anything the diff shows as added is
mine; anything it shows as unchanged is the original author's. No claim in this file has to be taken
on trust.

## Files retained and adapted

Four files survive from upstream. All four were modified: every Chinese comment and docstring was
translated to English, and the changes noted below were made. Each file carries an "Adapted from"
header naming its origin.

| File | Upstream path | What changed |
|---|---|---|
| `warehouse/macros/cross_db.sql` | same | Comments translated. Dispatch namespace changed from `quantai_warehouse` to `pm_bi_warehouse`. Three of five macros dropped (`iso_day_of_week`, `year_month`, `local_date_from_utc`) as inapplicable — private markets data has no trading calendar and no intraday UTC timestamps. `day_spine` and `asof_left_join` retained unchanged in logic. |
| `warehouse/macros/generate_schema_name.sql` | same | Comment translated. Logic unchanged. |
| `infra/snowflake/sfconn.py` | same | Docstring and comments translated. Object-name defaults changed from `QUANTAI_*` to this project's. `mask()` reworked: the S3 bucket and IAM ARN patterns were dropped (this project loads from a local internal stage, not a data lake) and the private key path is now masked instead. Reformatted by ruff. |
| `infra/snowflake/reconcile.py` | same | Docstring and comments translated. Query tag renamed to `pm-bi-reconcile`. Reformatted by ruff. One behavioural edit: both `zip` calls now pass `strict=` explicitly (`False` across rows, where a count mismatch is already reported as a problem; `True` across cells, where the column check makes a mismatch impossible and therefore a bug). The comparison arithmetic is otherwise untouched — the two-layer fingerprint-then-cell design, the exact-integer rule and the 1e-9 / 1e-12 tolerances are all the original author's. |

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

## Patterns reimplemented, not copied

These upstream ideas informed this project, but no code carried over. They are listed because the
influence is real and should be acknowledged, not because the files are shared.

| Pattern | Upstream source | How it is used here |
|---|---|---|
| Layered dbt project, `raw` → `staging` → `marts`, with staging as views and marts as tables, materialization set at directory level | `warehouse/dbt_project.yml` | Same layering, plus an `intermediate/` layer upstream did not have |
| Grain uniqueness enforced on every mart, by a `unique` test or a purpose-written singular test | `warehouse/models/marts/schema.yml` and `warehouse/tests/assert_*_unique_grain.sql` | Same discipline, extended with enforced model contracts, which upstream had none of |
| Integration test that seeds a warehouse, invokes `dbtRunner` programmatically, then reconciles SQL output against an independent Python implementation | `tests/warehouse/test_dbt_build.py` | Same shape, reconciling dbt-computed IRR, TVPI and DPI against `src/pm_bi/metrics/returns.py` |
| Snowflake raw load as a single transaction with rollback, refusing to load an incomplete snapshot | `infra/snowflake/load_raw.py` | Same transactional guarantee, rewritten for `PUT` to an internal stage instead of an S3 external stage |
| Cost control: XSMALL warehouse, `AUTO_SUSPEND = 60`, resource monitor with a small monthly quota and a suspend trigger | `infra/snowflake/admin_setup.sql` | Same, extended to a warehouse per workload and a LOADER / TRANSFORMER / REPORTER role split, where upstream had a single role |
| Power BI as code: semantic model in plain-text TMDL, report layout generated by a committed script, whole artifact diffable in git | `powerbi/` | Same principle, targeting PBIR rather than the legacy `report.json` upstream used |
| A hidden QA report page reconciling live DAX measures against expected values computed independently in Python, split into measure-arithmetic checks and model-wiring "relationship canary" checks | `powerbi/verify/verify_dax.py` and the QA page | Same two-class design. This is the single best idea inherited from upstream: its author found that all 53 arithmetic checks passed green while six relationships in the model were silently dead, and added the wiring class specifically to catch that. |
| CI secret hygiene: OIDC in place of long-lived credentials, account identifiers and endpoint IDs masked in logs, a fail-closed smoke test asserting an unauthenticated request is rejected | `.github/workflows/deploy.yml` | Same conventions applied to the Snowflake credentials in this project's PR and main workflows |

## Deliberately not carried over

Noted so the omissions read as decisions rather than oversights.

- **Business logic in DAX.** Upstream's `Rolling Vol 20D (Ann)`, `MA 20/50/200` and indexed-series
  measures rebuild 20-trading-row windows inside DAX with `TOPN` and `STDEVX.S`. That work is
  carefully done and well documented, but it puts business logic in the semantic model. This project
  computes metrics in dbt and keeps DAX measures thin, so the pattern is rejected on purpose.
- **The entire domain layer.** All 11 sources, all 21 models, all 10 marts, all 48 measures and all
  six visible report pages are public-equities constructs. None apply.
- **Data acquisition.** `yfinance`, RSS news ingestion and the Polymarket integration are gone.
  Private markets fund-level data is not publicly available, so this project generates seeded
  synthetic data instead — which also removes a live-network dependency that made the upstream ETL
  non-deterministic.
- **The AWS Lambda / SAM deployment stack and Terraform data lake.** Out of scope.

## License

Upstream is MIT, which permits this reuse provided the copyright notice and permission notice are
retained. `LICENSE` carries the original `Copyright (c) 2025 QuantAI` notice alongside the notice
for work added here. The four adapted files above remain subject to the original notice.
