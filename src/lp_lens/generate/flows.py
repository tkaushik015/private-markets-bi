"""Cash flows and NAV: the two tables that carry the actual fund behaviour.

They are generated together because NAV depends on the flows. Net asset value at a quarter end is
a function of how much has been paid in by then and how much has already been distributed, so
splitting them across modules would mean computing the cumulative flow position twice.

Sign convention
---------------
Every `amount` is a positive magnitude. Direction is carried by `flow_type`, never by the sign:

| flow_type                | LP cash direction | counts toward paid-in | adds callable headroom |
|--------------------------|-------------------|-----------------------|------------------------|
| capital_call             | LP pays out       | yes                   | no                     |
| management_fee           | LP pays out       | yes                   | no                     |
| distribution             | LP receives       | no                    | no                     |
| recallable_distribution  | LP receives       | no                    | yes                    |

Keeping amounts unsigned means a consumer cannot accidentally sum a mixed column and get a
meaningless number; it has to state which flow types it means. `FLOW_DIRECTION` gives the sign for
the one case that genuinely needs it, an IRR cash flow vector.

Generation order
----------------
Each commitment's full lifecycle is built first, from the vintage through to liquidation, and only
then truncated at the as-of date. That is what makes a 2024-vintage fund show a low paid-in
fraction and a deep J-curve trough at the as-of date without any special-casing for young funds:
it is early in a schedule that was drawn in full.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import numpy as np

from .config import GeneratorConfig
from .entities import Commitment, Fund, add_years, money

PAID_IN_TYPES: frozenset[str] = frozenset({"capital_call", "management_fee"})
DISTRIBUTION_TYPES: frozenset[str] = frozenset({"distribution", "recallable_distribution"})
FLOW_TYPES: tuple[str, ...] = (
    "capital_call",
    "management_fee",
    "distribution",
    "recallable_distribution",
)

# Sign from the LP's point of view, for building an IRR cash flow vector.
FLOW_DIRECTION: dict[str, int] = {
    "capital_call": -1,
    "management_fee": -1,
    "distribution": +1,
    "recallable_distribution": +1,
}

# Sort rank so that flows landing on the same date always order the same way. Without this the
# cumulative paid-in walk would depend on list insertion order, which is a silent determinism leak.
_TYPE_RANK: dict[str, int] = {name: i for i, name in enumerate(FLOW_TYPES)}

_QUARTER_ENDS: tuple[tuple[int, int], ...] = ((3, 31), (6, 30), (9, 30), (12, 31))


@dataclass
class _Event:
    flow_date: dt.date
    flow_type: str
    amount: float


def quarter_ends_between(start: dt.date, end: dt.date) -> list[dt.date]:
    """Every real quarter-end date q with start <= q <= end.

    Built from a literal month/day table rather than by date arithmetic, so a "quarter end" is
    always 31 March, 30 June, 30 September or 31 December and never an approximation.
    """
    out: list[dt.date] = []
    for year in range(start.year, end.year + 1):
        for month, day in _QUARTER_ENDS:
            q = dt.date(year, month, day)
            if start <= q <= end:
                out.append(q)
    return out


def _spread_dates(
    window_start: dt.date,
    window_end: dt.date,
    n: int,
    beta: tuple[float, float],
    rng: np.random.Generator,
) -> tuple[list[dt.date], np.ndarray]:
    """Place n dates in a window, skewed by a Beta draw, returned sorted with their progress.

    Beta(a, b) with a < b clusters draws near the start of the window and a > b near the end,
    which is how calls are front-loaded and distributions back-loaded.
    """
    if window_end <= window_start:
        window_end = window_start + dt.timedelta(days=1)
    span = (window_end - window_start).days
    u = np.sort(rng.beta(beta[0], beta[1], size=n))
    dates = [window_start + dt.timedelta(days=round(float(frac) * span)) for frac in u]
    return dates, u


def _weights(u: np.ndarray, tilt: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Positive weights summing to 1, combining a gamma draw with a deterministic tilt.

    The gamma draw supplies lumpiness, since real calls are not equal instalments; the tilt makes
    early calls larger and late distributions larger.
    """
    raw = rng.gamma(shape=2.0, scale=1.0, size=u.size) * tilt
    total = raw.sum()
    if total <= 0.0:
        return np.full(u.size, 1.0 / u.size)
    return raw / total


def _floor_cents(value: float) -> float:
    """Round down to cents. Used for the paid-in allowance so rounding can never breach the cap."""
    return math.floor(value * 100.0) / 100.0


def _build_commitment_events(
    config: GeneratorConfig,
    fund: Fund,
    commitment: Commitment,
    rng: np.random.Generator,
) -> list[_Event]:
    """Full-lifecycle flow schedule for one commitment, before the as-of truncation."""
    cfg = config.cash_flows
    amount = commitment.commitment_amount
    vintage_start = fund.vintage_start
    liquidation = fund.liquidation_date

    terminal_paid_in = amount * rng.uniform(*cfg.terminal_paid_in_fraction_range)

    # --- management fees: one per commitment anniversary, while the fund is alive -------------
    fee_dates = [
        d for k in range(cfg.management_fee_years) if (d := add_years(commitment.commitment_date, k)) <= liquidation
    ]
    fee_each = cfg.management_fee_rate * amount
    fee_total = fee_each * len(fee_dates)
    # Fees are drawn from the commitment, so they compete with calls for the same envelope. If a
    # long fee schedule on a low paid-in fraction would crowd calls out entirely, scale the fees
    # back rather than emitting a fund that is all fees and no investment.
    fee_cap = 0.6 * terminal_paid_in
    fee_scale = min(1.0, fee_cap / fee_total) if fee_total > 0.0 else 1.0
    fee_each *= fee_scale
    fee_total *= fee_scale

    # --- capital calls ------------------------------------------------------------------------
    call_total = max(terminal_paid_in - fee_total, 0.0)
    n_calls = int(rng.integers(cfg.calls_per_commitment_range[0], cfg.calls_per_commitment_range[1] + 1))
    call_window_end = min(add_years(vintage_start, cfg.call_period_years), liquidation)
    call_dates, call_u = _spread_dates(commitment.commitment_date, call_window_end, n_calls, cfg.call_beta, rng)
    # Tilt falls with progress, so the first calls are the large ones.
    call_weights = _weights(call_u, 1.0 - 0.5 * call_u, rng)

    # --- distributions ------------------------------------------------------------------------
    dist_total = fund.terminal_tvpi * terminal_paid_in
    n_dists = int(
        rng.integers(cfg.distributions_per_commitment_range[0], cfg.distributions_per_commitment_range[1] + 1)
    )
    dist_window_start = add_years(vintage_start, cfg.distribution_start_year)
    # Capped at the final quarter end so every distribution has settled by the time NAV goes to
    # zero. Allowing one to land after liquidation would show value leaving the fund after it had
    # already reported holding nothing.
    dist_window_end = min(add_years(vintage_start, cfg.distribution_end_year), liquidation)
    dist_dates, dist_u = _spread_dates(dist_window_start, dist_window_end, n_dists, cfg.distribution_beta, rng)
    # Tilt rises with progress, so the exits late in the fund's life are the big ones.
    dist_weights = _weights(dist_u, 0.5 + dist_u, rng)
    recallable_share = rng.uniform(*cfg.recallable_share_range)
    recallable_flags = rng.random(n_dists) < recallable_share

    events = [_Event(d, "management_fee", fee_each) for d in fee_dates]
    events += [_Event(d, "capital_call", call_total * w) for d, w in zip(call_dates, call_weights, strict=True)]
    events += [
        _Event(d, "recallable_distribution" if flag else "distribution", dist_total * w)
        for d, w, flag in zip(dist_dates, dist_weights, recallable_flags, strict=True)
    ]
    events.sort(key=lambda e: (e.flow_date, _TYPE_RANK[e.flow_type], e.amount))
    return events


def _apply_paid_in_cap(events: list[_Event], commitment_amount: float) -> list[_Event]:
    """Clip paid-in events so cumulative paid-in never exceeds commitment + recallable to date.

    Enforced here rather than left to the draw. The configured paid-in fraction is capped at 1.0,
    so the clip should never bind for the shipped config, but it is the invariant the marts will
    rely on and an invariant that holds only because of how the inputs happen to be tuned is not
    an invariant. Events clipped to zero are dropped rather than emitted, because a zero-amount
    cash flow would violate the amount > 0 rule.
    """
    kept: list[_Event] = []
    cum_paid_in = 0.0
    cum_recallable = 0.0
    for event in events:
        if event.flow_type in PAID_IN_TYPES:
            allowance = _floor_cents(commitment_amount + cum_recallable - cum_paid_in)
            amount = money(min(event.amount, max(allowance, 0.0)))
            if amount <= 0.0:
                continue
            cum_paid_in += amount
            kept.append(_Event(event.flow_date, event.flow_type, amount))
        else:
            amount = money(event.amount)
            if amount <= 0.0:
                continue
            if event.flow_type == "recallable_distribution":
                cum_recallable += amount
            kept.append(_Event(event.flow_date, event.flow_type, amount))
    return kept


def _nav_rows(
    config: GeneratorConfig,
    fund: Fund,
    commitment: Commitment,
    events: list[_Event],
    rng: np.random.Generator,
) -> list[dict]:
    """Quarter-end NAV for one commitment, from the first capital call to liquidation or as-of."""
    cfg = config.nav
    paid_in_events = [e for e in events if e.flow_type in PAID_IN_TYPES]
    call_events = [e for e in events if e.flow_type == "capital_call"]
    if not call_events:
        # No calls means nothing was ever invested, so there is no net asset value to report.
        # NULL-by-omission, not a zero row that would read as "valued at nothing".
        return []

    first_call = min(e.flow_date for e in call_events)
    liquidation = fund.liquidation_date
    last_quarter = min(liquidation, config.as_of_date)
    quarters = quarter_ends_between(first_call, last_quarter)
    if not quarters:
        return []

    life_days = max((liquidation - fund.vintage_start).days, 1)
    breakpoints = [0.0, cfg.trough_progress, 1.0]
    multiples = [cfg.initial_multiple, cfg.trough_multiple, fund.terminal_tvpi]
    noise = rng.normal(0.0, cfg.quarterly_noise_sd, size=len(quarters))

    rows: list[dict] = []
    for quarter_end, shock in zip(quarters, noise, strict=True):
        paid_in = sum(e.amount for e in paid_in_events if e.flow_date <= quarter_end)
        distributed = sum(e.amount for e in events if e.flow_type in DISTRIBUTION_TYPES and e.flow_date <= quarter_end)
        progress = min(max((quarter_end - fund.vintage_start).days / life_days, 0.0), 1.0)
        multiple = float(np.interp(progress, breakpoints, multiples)) * math.exp(shock)
        nav = paid_in * multiple - distributed
        if quarter_end == liquidation:
            # A fully liquidated fund holds nothing. The residual the curve would leave here is an
            # artefact of the noise term, not a real holding, so it is zeroed rather than reported.
            nav = 0.0
        rows.append(
            {
                "fund_id": fund.fund_id,
                "investor_id": commitment.investor_id,
                "quarter_end": quarter_end,
                "nav": money(max(nav, 0.0)),
                "currency": fund.currency,
            }
        )
    return rows


def build_cash_flows_and_nav(
    config: GeneratorConfig,
    funds: list[Fund],
    commitments: list[Commitment],
    flow_rng: np.random.Generator,
    nav_rng: np.random.Generator,
) -> tuple[list[dict], list[dict]]:
    """Build the cash_flows and nav tables, truncated at the as-of date."""
    fund_by_id = {f.fund_id: f for f in funds}
    cash_flows: list[dict] = []
    nav: list[dict] = []

    for commitment in commitments:
        fund = fund_by_id[commitment.fund_id]
        events = _build_commitment_events(config, fund, commitment, flow_rng)
        events = _apply_paid_in_cap(events, commitment.commitment_amount)

        # NAV needs the whole schedule to compute cumulative position, so it is built before the
        # as-of truncation and truncated on its own quarter-end grid inside _nav_rows.
        nav.extend(_nav_rows(config, fund, commitment, events, nav_rng))

        for event in events:
            if event.flow_date > config.as_of_date:
                continue
            cash_flows.append(
                {
                    "cash_flow_id": "",  # assigned below, once the final row order is known
                    "fund_id": fund.fund_id,
                    "investor_id": commitment.investor_id,
                    "flow_date": event.flow_date,
                    "flow_type": event.flow_type,
                    "amount": event.amount,
                    "currency": fund.currency,
                }
            )

    cash_flows.sort(key=lambda r: (r["fund_id"], r["investor_id"], r["flow_date"], _TYPE_RANK[r["flow_type"]]))
    for i, row in enumerate(cash_flows, start=1):
        row["cash_flow_id"] = f"CF{i:07d}"

    nav.sort(key=lambda r: (r["fund_id"], r["investor_id"], r["quarter_end"]))
    return cash_flows, nav
