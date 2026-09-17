# Synthetic private markets data generator

**All data produced here is fabricated.** No manager, fund or investor in the output is a real
entity, and no figure is a real reported number. Names are assembled from a fixed list of invented
English place-name stems in [`names.py`](names.py); any resemblance to a real firm is coincidental.

Private markets fund-level data is not publicly available at the LP position level, so LP Lens
generates its own. The generator also removes a live-network dependency: the audited predecessor
project pulled prices over the internet at build time, which made its ETL non-reproducible.

## Running it

```bash
python -m lp_lens.generate --config configs/generator.yaml --out data/raw
```

`data/raw/` is gitignored. Generated data is never committed — it is reproducible from the config
and the seed, so committing it would add megabytes to the repository to store something the code
already fully determines.

Add `--print-hashes` to print the SHA-256 of each file, which is how the determinism claim below
is checked by hand.

## Determinism

One seed in [`configs/generator.yaml`](../../../configs/generator.yaml) drives every draw. The same
seed and config produce **byte-identical** Parquet; a different seed changes all eight tables.

Four things make that hold, and all four are load-bearing:

1. Every draw comes from a `numpy.random.Generator` spawned from one `SeedSequence`
   ([`streams.py`](streams.py)). Nothing uses the global numpy random state.
2. Streams are independent per table, so drawing more numbers for cash flows cannot shift the FX
   series. Appending a new name to `STREAM_NAMES` leaves existing streams untouched; inserting one
   in the middle would renumber everything after it.
3. No wall clock. The as-of date is config, not `datetime.now()`, so the output does not depend on
   when it ran.
4. Parquet is written with declared schemas, pandas metadata stripped and write options pinned
   ([`writer.py`](writer.py)). Every table is sorted by its primary key before writing, so row
   order is fixed rather than incidental.

## Entities and grains

| Table | Grain | Rows (seed 20260630) |
|---|---|---|
| `managers` | one row per GP | 25 |
| `funds` | one row per fund | 60 |
| `investors` | one row per LP | 12 |
| `commitments` | one row per **investor × fund** | 156 |
| `cash_flows` | one row per **transaction** | 3,078 |
| `nav` | one row per **fund × investor × quarter end** | 4,454 |
| `fx_rates` | one row per **date × currency pair** | 5,295 |
| `public_index` | one row per **date × index** | 5,295 |

Note the two fact grains, because they differ from the equities shape this project replaced.
`cash_flows` is irregular: a transaction lands when it lands, and there is no row for a date with
no activity. `nav` is a regular quarterly grid. Both are keyed on a *pair* of entities, the fund
and the investor, not on a single instrument.

Every manager has at least one fund, so the manager dimension has no orphan rows. No investor
commits to the same fund twice, which is what makes `(investor_id, fund_id)` a natural key on
`commitments`.

## Sign convention

**Every `amount` is a positive magnitude. Direction is carried by `flow_type`, never by the sign.**

| `flow_type` | LP cash direction | counts toward paid-in | adds callable headroom |
|---|---|---|---|
| `capital_call` | LP pays out | yes | no |
| `management_fee` | LP pays out | yes | no |
| `distribution` | LP receives | no | no |
| `recallable_distribution` | LP receives | no | yes |

Unsigned amounts mean a consumer cannot sum a mixed column and get a meaningless number — it has
to say which flow types it means. For the one case that genuinely needs a sign, an IRR cash flow
vector, `FLOW_DIRECTION` in [`flows.py`](flows.py) gives it: `-1` for the paid-in types, `+1` for
the distribution types.

Management fees count toward paid-in because they are drawn from the commitment. That matters for
DPI and TVPI, whose denominator is paid-in capital, and it is the reason a young fund's TVPI sits
below 1.0 before any value has accrued.

## The lifecycle model

Each commitment gets a full lifecycle schedule, from the vintage through to liquidation, and only
then is everything truncated at the as-of date. That is why a 2024-vintage fund shows a low
paid-in fraction and a deep J-curve trough with no special-casing for young funds: it is simply
early in a schedule that was drawn in full.

**Capital calls** land in the first five years, placed by a `Beta(1.6, 2.4)` draw over the window,
which clusters them early. Their sizes carry a tilt that falls with time, so the first calls are
the largest. Measured on the shipped config and seed, 80% of called capital lands within three
years of the vintage.

**Management fees** fall on commitment anniversaries, 2% of commitment a year for up to ten years.
They compete with calls for the same envelope: total paid-in is drawn as 80–98% of commitment, and
if a long fee schedule would crowd calls out entirely the fees are scaled back rather than
emitting a fund that is all fees and no investment.

**Distributions** land between years 4 and 12, placed by a `Beta(2.4, 1.6)` draw, which clusters
them late, with a tilt that rises with time so the big exits come last. A share of them, 0–15% per
commitment, is marked recallable.

**Liquidation** is the fund's final quarter end, `31 December` of `vintage + life − 1`. It is a
quarter end on purpose: fund-life anniversaries fall on 1 January, which is not a quarter-end
date, so a NAV grid truncated at one would stop at the previous 31 December and never coincide
with liquidation — leaving a wound-up fund reporting whatever the J-curve happened to evaluate to
instead of the zero it must report.

## The J-curve and the spread of outcomes

NAV is not drawn directly. It is derived:

```
NAV(q) = max(0, paid_in_to_date(q) × multiple(q) − distributed_to_date(q))
```

`multiple(q)` is a piecewise-linear curve in fund-life progress, running from 0.95 at inception,
down to a trough of 0.80 at 18% of the fund's life, then up to the fund's terminal TVPI at
liquidation, with a small lognormal shock per quarter. Starting below 1.0 and dipping further is
what produces the early phase where paid-in exceeds value — fees are drawn before any value
accrues. At liquidation the identity closes: distributions have reached `TVPI × paid-in`, the
multiple has reached `TVPI`, and NAV is zero.

Every investor in the same fund sees the same multiple, scaled by their own paid-in, because fund
performance is a property of the fund, not of the position.

## Per-strategy outcome assumptions

Terminal TVPI at liquidation is drawn per fund as `exp(Normal(tvpi_log_mean, tvpi_log_sd))`, so
`exp(tvpi_log_mean)` is the median multiple and `tvpi_log_sd` sets the dispersion.

**These are invented assumptions, chosen to give the synthetic book a usable shape. They are not
calibrated to, and make no claim about, any real fund, index or industry data set.** Nothing here
should be read as a benchmark.

| Strategy | `tvpi_log_mean` | Median | `tvpi_log_sd` | Intent |
|---|---|---|---|---|
| Venture | 0.615 | 1.85x | **0.72** | widest: a real loss-making tail and a real 4x-plus tail in one cohort |
| Growth | 0.560 | 1.75x | 0.45 | wide, but less so than venture |
| Buyout | 0.588 | 1.80x | 0.34 | moderate dispersion around a solid centre |
| Real Estate | 0.438 | 1.55x | 0.28 | moderate |
| Secondaries | 0.372 | 1.45x | 0.18 | tight, the diversification is priced in |
| Infrastructure | 0.405 | 1.50x | 0.16 | second narrowest |
| Private Credit | 0.336 | 1.40x | **0.14** | narrowest: contractual, so little to disperse |

Two properties are deliberate, and both are asserted in
[`tests/test_generator.py`](../../../tests/test_generator.py) rather than left to inspection:

1. **Every strategy is centred above 1.0x.** A strategy centred at break-even makes its whole
   cohort indistinguishable from a fund that merely returned capital, which leaves the downstream
   metrics nothing to separate.
2. **Dispersion is ordered**, venture widest through private credit narrowest. Credit and
   infrastructure are tight enough around a positive centre that no fund in either is modelled
   below break-even — a narrow band and a positive centre at the same time, which is the point of
   how those two are calibrated. The downside in the book lives in the dispersed strategies.

### Modelled terminal vs realised at the as-of date

These are different quantities and it is worth being explicit, because the second is easy to
mistake for the first.

| Strategy | Funds | Modelled terminal TVPI (min / median / max) | Realised at as-of (min / median / max) |
|---|---|---|---|
| Buyout | 22 | 0.92 / 2.16 / 3.87 | 0.82 / 1.54 / 3.87 |
| Venture | 8 | 0.45 / 2.44 / 5.19 | 0.50 / 1.48 / 3.42 |
| Growth | 8 | 0.86 / 3.16 / 4.03 | 0.81 / 1.44 / 3.59 |
| Real Estate | 6 | 0.92 / 1.43 / 2.71 | 0.92 / 1.65 / 2.71 |
| Secondaries | 7 | 1.00 / 1.38 / 1.87 | 0.97 / 1.15 / 1.87 |
| Infrastructure | 4 | 1.21 / 1.33 / 1.56 | 1.02 / 1.07 / 1.20 |
| Private Credit | 5 | 1.21 / 1.31 / 1.47 | 0.88 / 1.24 / 1.46 |

Realised sits below terminal for any cohort still mid-life, because a fund part-way up the J-curve
has not yet earned its multiple. **Infrastructure is the clearest case:** its 11–14 year lives mean
none of its four funds has liquidated and the median is only about halfway through its life, so it
reads near break-even at the as-of date while being modelled at 1.33x terminal. That gap is the
J-curve, not the calibration — and it is why the tests assert the property on the modelled
distribution, where fund age cannot confound it.

Wherever the two *can* be compared they agree: for a fully liquidated fund nothing is left to
value, so realised TVPI is the final answer, and it matches the modelled terminal multiple to
within 3.4e-09 relative error across all 22 liquidated funds that carry commitments. That
agreement is what makes the modelled figure a legitimate stand-in for funds still running.

On the realised side, 15 of 59 funds with commitments sit below 1.0x and 15 above 2.0x. 24 are
fully liquidated, and for those TVPI equals DPI by definition, since no residual value remains.
One fund, `FUND0007`, drew no commitments from this 12-investor universe and so has no realised
figure at all.

Median realised TVPI by vintage traces the J-curve across the book: 0.85 for 2024, 0.97 for 2023,
1.20 for 2021, 1.49 for 2017, and 1.84–2.87 for 2012–2016.

## Reference series

`fx_rates` and `public_index` are **calendar-daily**, covering every date from 1 January of the
earliest vintage to the as-of date. Calendar-daily rather than business-daily is deliberate: 30
June 2024 is a Sunday, and a business-day series would leave a EUR-denominated NAV on that date
with no rate to convert it at. Generating every date makes "FX covers every date with a EUR flow
or NAV" true by construction, rather than by a nearest-previous-rate rule that would then have to
be reimplemented identically in dbt and in Python.

EUR→USD is a mean-reverting log process rather than a random walk, because over fourteen years a
driftless walk at 8% annual vol wanders to implausible levels, and clipping it to a band would
pile probability mass on the bounds. The public index is geometric Brownian motion with drift, and
is a **total-return** series, so a PME calculation indexes onto it with no dividend adjustment.

## Enforced invariants

These hold in the generator and each is asserted separately in
[`tests/test_generator.py`](../../../tests/test_generator.py):

- cumulative paid-in never exceeds commitment plus recallable distributions received **to that
  point** — checked at every flow, not just at the end, because a mid-life breach that a later
  distribution masks is still a breach
- `nav >= 0`; every `amount > 0`
- no cash flow before its commitment date; nothing at all after the as-of date
- every foreign key resolves, including `cash_flows` and `nav` resolving to a real
  `(fund, investor)` commitment pair
- primary keys unique and not null on all eight tables
- `quarter_end` values are real quarter-end dates, built from a literal month/day table
- no NAV before the first capital call, and none after liquidation — a series that ends before the
  as-of quarter must end at zero
- FX covers every date carrying a EUR flow or NAV
- every strategy's median modelled terminal TVPI is above 1.0x
- venture is the most dispersed strategy, and credit and infrastructure the two least, measured as
  the sample standard deviation of log terminal TVPI — scale-free, so a strategy with 22 funds is
  not flattered against one with 4
- the dispersed strategies still carry a loss-making tail, so raising every centre above 1.0x did
  not remove the downside from the book
- a fully liquidated fund's realised TVPI equals its modelled terminal multiple

The paid-in cap is enforced by a runtime clip in `_apply_paid_in_cap`, not left to the draw. The
configured paid-in fraction is capped at 1.0 so the clip should never bind, but an invariant that
holds only because the inputs happen to be tuned a certain way is not an invariant.

## What is deliberately not in the output

`Fund` carries two fields the Parquet does not: `life_years` and `terminal_tvpi`. They are
generator ground truth. Publishing the target multiple would let a downstream model read the
answer off the raw layer instead of computing it, and the tests are stronger for having to derive
realised TVPI from the cash flows and NAV the way a consumer would.
