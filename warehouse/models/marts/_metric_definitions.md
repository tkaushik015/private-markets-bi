{% docs as_of_convention %}
**As-of convention: inception-to-date as at `as_of_quarter`.** Every amount is the cumulative total
of all flows dated on or before that quarter end, and every ratio is built from those cumulative
totals. Nothing here is a single quarter's movement, and nothing includes a flow dated after the
quarter. The row for 2020-Q4 shows what the position looked like on 31 December 2020, using only
what was known by then.

**Net to the LP, with one stated limit.** Management fees are treated as paid-in capital, so every
multiple and rate is measured after the fee drag an LP actually bears. Carried interest is **not**
modelled: the Phase 1 generator produces capital calls, management fees, distributions and
recallable distributions, and no carry. So "net" means net of management fees and net of the
distribution schedule as modelled, not net of carry. Calling these figures fully net-of-carry would
overstate what the data contains.
{% enddocs %}

{% docs metric_dpi %}
**DPI, distributions to paid-in.** `distributions_usd / paid_in_usd`, where distributions are
distributions plus recallable distributions and paid-in is capital calls plus management fees. The
realised half of the return: cash actually back in the LP's hands per dollar drawn.

Inception-to-date as at `as_of_quarter`. NULL, not zero, where paid-in is zero -- a position drawn
nothing has no multiple rather than a multiple of nothing.

Net to the LP: management fees are in the denominator, so this is measured after fee drag. Carried
interest is not modelled in the source data, so it is not net of carry.
{% enddocs %}

{% docs metric_rvpi %}
**RVPI, residual value to paid-in.** `nav_usd / paid_in_usd`. The unrealised half of the return:
what is still held, per dollar drawn. Goes to zero for a fully liquidated position, which holds
nothing.

Inception-to-date as at `as_of_quarter`. NULL, not zero, where paid-in is zero.

Net to the LP: management fees are in the denominator. Carried interest is not modelled in the
source data, so it is not net of carry.
{% enddocs %}

{% docs metric_tvpi %}
**TVPI, total value to paid-in.** `(distributions_usd + nav_usd) / paid_in_usd`, which equals
`dpi + rvpi` by construction since all three share the paid-in denominator. That identity is
asserted by the `tvpi_equals_dpi_plus_rvpi` test rather than assumed.

Computed as a **ratio of sums, never an average of ratios**. At portfolio level in particular, the
average of a set of fund TVPIs weights a USD 2m position the same as a USD 200m one and answers a
question nobody asked.

Inception-to-date as at `as_of_quarter`. NULL, not zero, where paid-in is zero.

Net to the LP: management fees are in the denominator. Carried interest is not modelled in the
source data, so it is not net of carry.
{% enddocs %}

{% docs metric_net_irr %}
**Net IRR, annualised money-weighted return.** The rate `r` solving
`sum(flow_i / (1 + r) ** years_i) = 0` over every signed flow dated on or before `as_of_quarter`,
with residual NAV appended as a positive flow on the quarter-end date. Capital calls and
management fees are negative; distributions are positive. Day count is actual/365.

Solved in Python by `lp_lens.metrics.returns.xirr` -- Newton with a Brent fallback on a bracketing
grid -- and read into the warehouse by the `int_returns_by_quarter` model. There is no second
implementation in SQL, so the mart and the reconciliation test cannot disagree about the formula.

**NULL, never 0, when no rate exists.** A position that has only ever paid in has no IRR, and zero
would read as "broke even" rather than "could not be computed". Same-day flows are netted before
the sign test, so a capital call and a NAV of similar size on one date correctly produce NULL
rather than a spurious root.

At portfolio level the rate is solved over every flow of every position pooled into a single
vector. IRR is not additive: no average of fund IRRs, weighted or otherwise, equals the rate the
pooled stream produced.

Net to the LP: management fees are among the negative flows. Carried interest is not modelled in
the source data, so it is not net of carry.
{% enddocs %}

{% docs metric_ks_pme %}
**KS-PME, Kaplan-Schoar public market equivalent.**
`(sum(distribution_t * I_T / I_t) + NAV_T) / sum(contribution_t * I_T / I_t)`, where `I_t` is the
public index level on the flow date and `I_T` the level on `as_of_quarter`.

Each flow is future-valued to the as-of date by the index, so the comparison is against investing
the same cash on the same dates in the index instead. Above 1.0 means the fund beat the index on
that timing; below means it did not. NAV enters the numerator undiscounted because it is already
measured at the as-of date.

The benchmark is the synthetic total-return index from the Phase 1 generator. Total return means
the level already includes reinvested income, so no dividend adjustment is applied. **It is not a
real index and represents no real market.**

NULL where no contribution has been made, since dividing by zero invested capital is undefined.

Net to the LP: management fees are among the contributions. Carried interest is not modelled in the
source data, so it is not net of carry.
{% enddocs %}

{% docs metric_unfunded %}
**Unfunded commitment.** `commitment_usd + recallable_distributions_usd - paid_in_usd`.

Recallable distributions raise the ceiling rather than reducing the draw: capital returned on a
recallable basis restores callable headroom, so it increases what the GP may still call. This is
the same ceiling the `paid_in_lte_commitment_plus_recallable` test enforces from the other side.

Inception-to-date as at `as_of_quarter`.
{% enddocs %}

{% docs metric_paid_in %}
**Paid-in capital.** Capital calls plus management fees, cumulative to `as_of_quarter`.

Fees are included because they are drawn from the commitment, so an LP has genuinely paid them in.
That is also why a young position sits below 1.0x TVPI before any value has accrued: fees are paid
before the portfolio is worth anything. Excluding them would flatter every early-life multiple.
{% enddocs %}

{% docs metric_commitment %}
**Committed capital, in USD.** Converted at the FX rate on the **commitment date**, the date the
obligation was struck -- not at each reporting quarter's rate. Converting at the reporting date
would make unfunded commitment move with FX in a quarter with no capital activity at all.
{% enddocs %}
