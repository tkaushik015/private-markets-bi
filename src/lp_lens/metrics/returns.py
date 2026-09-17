"""IRR and PME over irregularly dated private markets cash flows.

Nothing here is recomputed anywhere else. The dbt Python models import these functions and the
reconciliation tests call them directly, so a mart and its expected value cannot disagree about
the formula -- there is only one formula.

Conventions, stated once and applied everywhere
-----------------------------------------------
**Sign.** Amounts passed to these functions are signed from the LP's point of view: capital calls
and management fees are negative, distributions positive. The Parquet layer stores unsigned
magnitudes with the direction in ``flow_type``; ``lp_lens.generate.FLOW_DIRECTION`` maps between
the two. Keeping the raw layer unsigned and signing it once, here, means the sign convention has a
single owner.

**Day count.** Actual/365. Year fractions are ``(date - first_date).days / 365.0``, so a leap year
is 366/365 of a year. Actual/365 is the convention Excel's XIRR uses, which makes a spot check
against a spreadsheet meaningful.

**Terminal NAV.** For a fund still holding assets, residual value is treated as a positive flow on
the as-of date. Without it a mid-life fund would show the IRR of a stream that only ever paid out,
which is meaningless. ``build_lp_flow_vector`` is the one place that appends it.

**Failure is None, never zero.** An IRR that cannot be computed returns ``None``, which surfaces as
NULL. Returning 0.0 would read as "the fund broke even" rather than "this could not be computed",
and those are very different statements to put in front of an investor.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence

DAYS_PER_YEAR = 365.0

# Newton is the fast path. These bound how hard it tries before the bracketing search takes over.
_MAX_NEWTON_ITER = 100
_RATE_STEP_TOL = 1e-12
# NPV is judged against the gross size of the stream, not in absolute currency. A residual of one
# cent is convergence on a EUR 500m fund and nowhere near it on a EUR 100 one.
#
# Only Newton is held to this. Near a deeply negative rate the NPV curve is close to vertical --
# the discount base is a few hundredths, so a change in r of 1e-12 moves NPV by millions -- and a
# residual test there rejects roots that are in fact located to full double precision. Brent is
# accepted on its bracket instead; see _brent.
_NPV_REL_TOL = 1e-9
# A rate at or below -100% would mean a negative discount base, which has no meaning here.
_MIN_RATE = -0.9999999
# Newton on a badly conditioned stream can run away to 1e90 and beyond, where the discount factors
# overflow. Anything past this ceiling is not a fund return, so treat reaching it as failure and
# let the bracketing search decide whether a real root exists.
_MAX_RATE = 1e6

# Grid for the bracketing search, ordered. Dense near zero where real fund IRRs live, and stretched
# far out on both sides so a pathological stream still gets a chance to bracket a root.
_BRACKET_GRID: tuple[float, ...] = (
    -0.999999,
    -0.99,
    -0.95,
    -0.9,
    -0.8,
    -0.7,
    -0.6,
    -0.5,
    -0.4,
    -0.3,
    -0.2,
    -0.1,
    -0.05,
    -0.01,
    0.0,
    0.01,
    0.05,
    0.1,
    0.15,
    0.2,
    0.3,
    0.4,
    0.5,
    0.75,
    1.0,
    1.5,
    2.0,
    3.0,
    5.0,
    10.0,
    25.0,
    50.0,
    100.0,
)


def _net_by_date(dates: Sequence[dt.date], amounts: Sequence[float]) -> tuple[list[dt.date], list[float]]:
    """Sum flows that land on the same date, returned in date order.

    Netting first is what makes the sign-change test mean what it should. A position holding a
    EUR 17m capital call and a EUR 17.1m NAV on the same day has no positive flow in economic
    terms -- the two offset -- but as separate rows it looks like a stream with both signs, and the
    solver would then be sent looking for a root that does not exist. Netting also makes the result
    independent of the order SQL happened to return the rows in.
    """
    totals: dict[dt.date, float] = {}
    for date, amount in zip(dates, amounts, strict=True):
        totals[date] = totals.get(date, 0.0) + float(amount)
    ordered = sorted(totals)
    return ordered, [totals[d] for d in ordered]


def _year_fractions(dates: Sequence[dt.date]) -> list[float]:
    origin = min(dates)
    return [(d - origin).days / DAYS_PER_YEAR for d in dates]


def _npv(rate: float, years: Sequence[float], amounts: Sequence[float]) -> float:
    """NPV at `rate`, or NaN where the discount factors are not representable.

    NaN rather than an exception: a diverging Newton iteration reaching an unrepresentable rate is
    an ordinary outcome of a badly conditioned stream, and the caller's job is to fall back to the
    bracketing search, not to handle an error.
    """
    base = 1.0 + rate
    if base <= 0.0:
        return math.nan
    total = 0.0
    try:
        for t, amount in zip(years, amounts, strict=True):
            total += amount / base**t
    except OverflowError:
        return math.nan
    return total


def _npv_derivative(rate: float, years: Sequence[float], amounts: Sequence[float]) -> float:
    base = 1.0 + rate
    if base <= 0.0:
        return math.nan
    total = 0.0
    try:
        for t, amount in zip(years, amounts, strict=True):
            total += -t * amount / base ** (t + 1.0)
    except OverflowError:
        return math.nan
    return total


def _has_sign_change(amounts: Sequence[float]) -> bool:
    """True only if the stream contains both a strictly positive and a strictly negative amount.

    Without both, NPV is monotone in the same direction everywhere and no root exists. This is the
    check that turns "an LP that only ever paid in" into NULL rather than into a spurious number.
    """
    return any(a > 0.0 for a in amounts) and any(a < 0.0 for a in amounts)


def _converged(rate: float, years: Sequence[float], amounts: Sequence[float], scale: float) -> bool:
    value = _npv(rate, years, amounts)
    return math.isfinite(value) and abs(value) <= _NPV_REL_TOL * scale


def _newton(years: Sequence[float], amounts: Sequence[float], scale: float, guess: float) -> float | None:
    rate = guess
    for _ in range(_MAX_NEWTON_ITER):
        value = _npv(rate, years, amounts)
        slope = _npv_derivative(rate, years, amounts)
        if not math.isfinite(value) or not math.isfinite(slope) or slope == 0.0:
            return None
        step = value / slope
        nxt = rate - step
        if nxt <= _MIN_RATE:
            # Newton overshot out of the valid domain. Halve the distance to the floor instead of
            # abandoning, which lets a steep early iteration recover rather than fail.
            nxt = (rate + _MIN_RATE) / 2.0
        elif nxt > _MAX_RATE:
            return None
        if abs(nxt - rate) <= _RATE_STEP_TOL * max(1.0, abs(rate)):
            return nxt if _converged(nxt, years, amounts, scale) else None
        rate = nxt
    return rate if _converged(rate, years, amounts, scale) else None


def _brent(years: Sequence[float], amounts: Sequence[float]) -> float | None:
    """Bracket a sign change on a fixed grid, then hand the bracket to Brent.

    Scanning a grid rather than trusting an interval means a stream whose IRR sits far from the
    initial guess is still found, and a stream with no real root is correctly reported as having
    none instead of returning whatever the last Newton iteration happened to hold.

    The root is accepted on the strength of the bracket rather than re-tested against an NPV
    threshold. NPV is continuous on (-1, inf), so a strict sign change across the interval
    guarantees a root inside it and Brent is guaranteed to converge to one. Re-testing the residual
    would reject legitimate deeply-negative rates, where the curve is so steep that a root located
    to full double precision in r still leaves a large residual in NPV. A young position that
    called capital and is carrying it below cost really does have an IRR near -95%, and reporting
    that is more use than reporting NULL.
    """
    from scipy.optimize import brentq

    previous_rate = _BRACKET_GRID[0]
    previous_value = _npv(previous_rate, years, amounts)
    for rate in _BRACKET_GRID[1:]:
        value = _npv(rate, years, amounts)
        if math.isfinite(previous_value) and math.isfinite(value) and previous_value * value < 0.0:
            try:
                root = float(brentq(_npv, previous_rate, rate, args=(years, amounts), maxiter=200))
            except (ValueError, RuntimeError):
                return None
            return root if math.isfinite(root) else None
        previous_rate, previous_value = rate, value
    return None


def xirr(
    dates: Sequence[dt.date],
    amounts: Sequence[float],
    *,
    guess: float = 0.1,
) -> float | None:
    """Internal rate of return over irregularly spaced dates, as an annual rate.

    Solves ``sum(amount_i / (1 + r) ** years_i) = 0`` with Newton, falling back to Brent on a
    bracketing grid when Newton does not converge.

    Returns ``None``, never ``0.0``, when the rate does not exist or cannot be found: fewer than
    two flows, no sign change, or no real root. A stream like ``[-1000, +2500, -2000]`` has a
    negative discriminant and genuinely has no real IRR; that is a NULL, not a zero.

    Multiple sign changes can admit several roots. The grid is scanned from the most negative rate
    upward and the first root found is returned, so the answer is at least deterministic.
    """
    if len(dates) != len(amounts):
        raise ValueError(f"dates and amounts must be the same length, got {len(dates)} and {len(amounts)}")
    if len(amounts) < 2:
        return None

    netted_dates, netted_amounts = _net_by_date(dates, amounts)
    if len(netted_amounts) < 2:
        # Everything landed on one day. There is no time over which to earn a return, so a rate is
        # undefined however the amounts net out.
        return None
    if not _has_sign_change(netted_amounts):
        return None

    scale = sum(abs(a) for a in netted_amounts)
    if scale == 0.0:
        return None

    years = _year_fractions(netted_dates)
    found = _newton(years, netted_amounts, scale, guess)
    if found is None:
        found = _brent(years, netted_amounts)
    if found is None:
        return None
    return found if math.isfinite(found) else None


def ks_pme(
    amounts: Sequence[float],
    index_levels: Sequence[float],
    *,
    nav: float,
    terminal_index_level: float,
) -> float | None:
    """Kaplan-Schoar PME: what the fund returned against the same cash flows in a public index.

    Every flow is future-valued to the as-of date by the index, then distributions plus residual
    NAV are divided by contributions::

        KS-PME = (sum(D_t * I_T / I_t) + NAV_T) / sum(C_t * I_T / I_t)

    ``amounts`` is signed LP-view, so contributions are the negative entries and distributions the
    positive ones. ``index_levels[i]`` is the index level on the date of ``amounts[i]``.

    Above 1.0 means the fund beat the index on the same timing of cash; below means it did not.
    NAV enters the numerator undiscounted because it is already measured at the as-of date --
    future-valuing it would be scaling it by ``I_T / I_T``.

    Returns ``None`` when no contribution has been made, since dividing by zero invested capital is
    undefined rather than infinite.
    """
    if len(amounts) != len(index_levels):
        raise ValueError(
            f"amounts and index_levels must be the same length, got {len(amounts)} and {len(index_levels)}"
        )
    if terminal_index_level <= 0.0:
        raise ValueError(f"terminal_index_level must be positive, got {terminal_index_level}")

    future_valued_contributions = 0.0
    future_valued_distributions = 0.0
    for amount, level in zip(amounts, index_levels, strict=True):
        if level <= 0.0:
            raise ValueError(f"index levels must be positive, got {level}")
        factor = terminal_index_level / level
        if amount < 0.0:
            future_valued_contributions += -amount * factor
        else:
            future_valued_distributions += amount * factor

    if future_valued_contributions <= 0.0:
        return None
    return (future_valued_distributions + nav) / future_valued_contributions


def build_lp_flow_vector(
    flow_dates: Sequence[dt.date],
    signed_amounts: Sequence[float],
    *,
    as_of_date: dt.date,
    nav: float,
) -> tuple[list[dt.date], list[float]]:
    """Assemble the IRR cash flow vector for one position, with residual NAV as a terminal flow.

    Factored out because both the dbt Python model and the reconciliation test need exactly this
    vector. If each built its own, the two could disagree about whether NAV was included and the
    reconciliation would be comparing different questions.

    A zero NAV appends nothing. A liquidated fund has no residual value, and a zero-amount flow on
    the as-of date would only add a term that contributes nothing to the NPV while making the
    vector look as though a transaction occurred.
    """
    dates = list(flow_dates)
    amounts = [float(a) for a in signed_amounts]
    if nav > 0.0:
        dates.append(as_of_date)
        amounts.append(float(nav))
    return dates, amounts
