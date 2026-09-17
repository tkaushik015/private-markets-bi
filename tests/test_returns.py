"""Tests for the IRR and PME implementations.

The XIRR cases come from `tests/fixtures/xirr_cases.csv`, whose expected values were computed
without this module: closed forms where a two-flow stream admits one, and an independently written
bisection for the multi-flow case. The fixture carries the provenance of each figure in its
`expected_source` column, so a reader can check where the number came from rather than trusting
that it was produced correctly.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
from pathlib import Path

import pytest

from lp_lens.metrics.returns import build_lp_flow_vector, ks_pme, xirr

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "xirr_cases.csv"


def _load_cases() -> list[dict]:
    with FIXTURE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, "the XIRR fixture is empty"
    cases = []
    for row in rows:
        cases.append(
            {
                "case_id": row["case_id"],
                "description": row["description"],
                "expected": float(row["expected_xirr"]) if row["expected_xirr"].strip() else None,
                "source": row["expected_source"],
                "dates": [dt.date.fromisoformat(d) for d in row["dates"].split("|")],
                "amounts": [float(a) for a in row["amounts"].split("|")],
            }
        )
    return cases


CASES = _load_cases()
COMPUTABLE = [c for c in CASES if c["expected"] is not None]
UNDEFINED = [c for c in CASES if c["expected"] is None]


def test_fixture_covers_the_required_edge_cases() -> None:
    """Guards the fixture itself. If a case is renamed or dropped, the suite should say so rather
    than quietly testing less than it used to."""
    ids = {c["case_id"] for c in CASES}
    required = {
        "single_flow",
        "all_negative",
        "same_day_flows",
        "same_day_only",
        "nav_only_young_fund",
        "non_converging",
    }
    assert required <= ids, f"fixture is missing required cases: {sorted(required - ids)}"
    assert COMPUTABLE and UNDEFINED, "the fixture needs both computable and undefined cases"
    for case in CASES:
        assert case["source"].strip(), f"{case['case_id']} does not say where its expected value came from"


@pytest.mark.parametrize("case", COMPUTABLE, ids=lambda c: c["case_id"])
def test_xirr_matches_independently_computed_value(case: dict) -> None:
    result = xirr(case["dates"], case["amounts"])
    assert result is not None, f"{case['case_id']} returned None but should compute to {case['expected']}"
    assert result == pytest.approx(case["expected"], rel=1e-9, abs=1e-12), case["description"]


@pytest.mark.parametrize("case", UNDEFINED, ids=lambda c: c["case_id"])
def test_xirr_returns_none_when_no_rate_exists(case: dict) -> None:
    """The headline honesty rule: an uncomputable IRR is None, which becomes NULL.

    Asserting `is None` rather than falsiness on purpose -- 0.0 is falsy, and 0.0 is exactly the
    wrong answer here, because it reads as "broke even" instead of "could not be computed".
    """
    result = xirr(case["dates"], case["amounts"])
    assert result is None, f"{case['case_id']} returned {result!r}; expected None ({case['source']})"


def test_xirr_never_returns_zero_for_a_loss_making_stream() -> None:
    """A fund that called capital and returned a fraction of it must report a negative rate."""
    result = xirr([dt.date(2020, 1, 1), dt.date(2025, 1, 1)], [-1000.0, 400.0])
    assert result is not None and result < 0.0, f"expected a negative rate, got {result!r}"


def test_xirr_is_insensitive_to_flow_order() -> None:
    """Flows arrive from SQL in whatever order the engine returns them, so the result must not
    depend on that order."""
    dates = [dt.date(2018, 3, 15), dt.date(2019, 6, 30), dt.date(2024, 12, 31)]
    amounts = [-1000.0, -500.0, 2200.0]
    forward = xirr(dates, amounts)
    reverse = xirr(list(reversed(dates)), list(reversed(amounts)))
    assert forward is not None and reverse is not None
    assert forward == pytest.approx(reverse, rel=1e-12)


def test_xirr_nets_same_day_flows_before_testing_for_a_sign_change() -> None:
    """A call and a NAV of almost the same size on the same day offset each other.

    This position looks like a mixed-sign stream row by row, but once the same-day amounts are
    netted every flow is negative and no rate exists. Taken from a real position in the generated
    data, which is where the behaviour was found: without netting, the solver is sent hunting for a
    root that is not there, and whether it returns a number depends on where the search happens to
    land.
    """
    dates = [dt.date(2021, 4, 10), dt.date(2022, 3, 31), dt.date(2022, 3, 31)]
    amounts = [-2_259_349.36, -17_402_320.14, 17_114_335.22]
    assert sum(amounts) < 0
    assert xirr(dates, amounts) is None

    # Nudge the NAV above the call and a root appears, confirming the None above is about the
    # netted signs and not about same-day dates being mishandled.
    assert xirr(dates, [-2_259_349.36, -17_402_320.14, 21_000_000.00]) is not None


def test_xirr_reports_extreme_negative_rates_rather_than_null() -> None:
    """A position carrying called capital below cost early in its life has a genuinely severe
    annualised rate. Brent locates it on its bracket; the answer is a large negative number, and
    reporting it is more use than reporting NULL."""
    result = xirr(
        [dt.date(2019, 8, 28), dt.date(2020, 3, 20), dt.date(2020, 3, 31)],
        [-1_930_924.39, -14_121_805.07, 13_101_509.26],
    )
    assert result is not None, "a bracketed root was rejected"
    assert -1.0 < result < -0.5, f"expected a severe negative rate, got {result}"


def test_xirr_is_scale_invariant() -> None:
    """Scaling every amount by a constant leaves the rate unchanged. This also checks the
    convergence test is relative to stream size rather than an absolute currency threshold."""
    dates = [dt.date(2017, 1, 31), dt.date(2020, 7, 15), dt.date(2026, 6, 30)]
    small = xirr(dates, [-100.0, -50.0, 260.0])
    large = xirr(dates, [-100_000_000.0, -50_000_000.0, 260_000_000.0])
    assert small is not None and large is not None
    assert small == pytest.approx(large, rel=1e-9)


def test_xirr_rejects_mismatched_input_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        xirr([dt.date(2020, 1, 1)], [-1.0, 2.0])


def test_xirr_solves_from_a_hostile_initial_guess() -> None:
    """Newton from a far-off guess should either converge or hand over to the bracketing search;
    either way the answer must be the same one."""
    dates = [dt.date(2015, 1, 1), dt.date(2016, 1, 1), dt.date(2020, 1, 1)]
    amounts = [-1000.0, -200.0, 3000.0]
    baseline = xirr(dates, amounts)
    assert baseline is not None
    for guess in (-0.95, -0.5, 0.0, 5.0, 50.0):
        assert xirr(dates, amounts, guess=guess) == pytest.approx(baseline, rel=1e-9), (
            f"guess {guess} produced a different root"
        )


# --------------------------------------------------------------------------------------------
# build_lp_flow_vector
# --------------------------------------------------------------------------------------------


def test_flow_vector_appends_nav_as_a_terminal_flow() -> None:
    dates, amounts = build_lp_flow_vector([dt.date(2020, 3, 31)], [-1000.0], as_of_date=dt.date(2026, 6, 30), nav=450.0)
    assert dates == [dt.date(2020, 3, 31), dt.date(2026, 6, 30)]
    assert amounts == [-1000.0, 450.0]


def test_flow_vector_omits_a_zero_nav() -> None:
    """A liquidated fund holds nothing. Appending a zero would imply a transaction on the as-of
    date that never happened, while contributing nothing to the NPV."""
    dates, amounts = build_lp_flow_vector(
        [dt.date(2020, 3, 31), dt.date(2024, 9, 30)],
        [-1000.0, 1500.0],
        as_of_date=dt.date(2026, 6, 30),
        nav=0.0,
    )
    assert dates == [dt.date(2020, 3, 31), dt.date(2024, 9, 30)]
    assert amounts == [-1000.0, 1500.0]


def test_flow_vector_does_not_mutate_its_inputs() -> None:
    original_dates = [dt.date(2020, 3, 31)]
    original_amounts = [-1000.0]
    build_lp_flow_vector(original_dates, original_amounts, as_of_date=dt.date(2026, 6, 30), nav=10.0)
    assert original_dates == [dt.date(2020, 3, 31)]
    assert original_amounts == [-1000.0]


# --------------------------------------------------------------------------------------------
# KS-PME
# --------------------------------------------------------------------------------------------


def test_ks_pme_of_one_when_the_fund_tracks_the_index() -> None:
    """Call 100 at index 100, distribute 200 at index 200, nothing left. The fund did exactly what
    the index did, so PME is 1.0 to the digit."""
    result = ks_pme([-100.0, 200.0], [100.0, 200.0], nav=0.0, terminal_index_level=200.0)
    assert result == pytest.approx(1.0, rel=1e-12)


def test_ks_pme_above_one_when_the_fund_beats_the_index() -> None:
    """Contribution future-valued: 100 * 200/100 = 200. Distribution is already at T: 300.
    So PME = 300 / 200 = 1.5."""
    result = ks_pme([-100.0, 300.0], [100.0, 200.0], nav=0.0, terminal_index_level=200.0)
    assert result == pytest.approx(1.5, rel=1e-12)


def test_ks_pme_below_one_when_the_fund_lags_the_index() -> None:
    result = ks_pme([-100.0, 150.0], [100.0, 200.0], nav=0.0, terminal_index_level=200.0)
    assert result == pytest.approx(0.75, rel=1e-12)


def test_ks_pme_counts_nav_undiscounted() -> None:
    """NAV is already measured at the as-of date, so it enters the numerator as-is. Contribution
    future-values to 100 * 150/100 = 150; numerator is 0 distributed + 180 NAV; PME = 1.2."""
    result = ks_pme([-100.0], [100.0], nav=180.0, terminal_index_level=150.0)
    assert result == pytest.approx(1.2, rel=1e-12)


def test_ks_pme_is_none_without_any_contribution() -> None:
    """No capital at risk means the ratio has a zero denominator, which is undefined rather than
    infinite -- so NULL, not a number."""
    assert ks_pme([200.0], [100.0], nav=0.0, terminal_index_level=100.0) is None
    assert ks_pme([], [], nav=0.0, terminal_index_level=100.0) is None


def test_ks_pme_is_invariant_to_index_rebasing() -> None:
    """Doubling every index level, terminal included, changes no ratio. PME depends on the shape of
    the index, not on its base, and a test that passes only at base 100 would be hiding a bug."""
    amounts = [-100.0, -50.0, 90.0]
    levels = [100.0, 120.0, 180.0]
    base = ks_pme(amounts, levels, nav=60.0, terminal_index_level=200.0)
    rebased = ks_pme(amounts, [x * 2 for x in levels], nav=60.0, terminal_index_level=400.0)
    assert base is not None and rebased is not None
    assert base == pytest.approx(rebased, rel=1e-12)


def test_ks_pme_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError, match="same length"):
        ks_pme([-100.0, 50.0], [100.0], nav=0.0, terminal_index_level=100.0)
    with pytest.raises(ValueError, match="terminal_index_level must be positive"):
        ks_pme([-100.0], [100.0], nav=0.0, terminal_index_level=0.0)
    with pytest.raises(ValueError, match="index levels must be positive"):
        ks_pme([-100.0], [0.0], nav=0.0, terminal_index_level=100.0)


def test_ks_pme_and_xirr_agree_on_direction() -> None:
    """Sanity cross-check between the two metrics: a stream that beat a flat index must also have
    a positive IRR. With a flat index every future-value factor is 1, so PME reduces to TVPI."""
    dates = [dt.date(2019, 1, 1), dt.date(2024, 1, 1)]
    amounts = [-1000.0, 1600.0]
    flat_levels = [100.0, 100.0]
    pme = ks_pme(amounts, flat_levels, nav=0.0, terminal_index_level=100.0)
    rate = xirr(dates, amounts)
    assert pme == pytest.approx(1.6, rel=1e-12), "against a flat index, PME is just TVPI"
    assert rate is not None and rate > 0.0
    assert math.isfinite(rate)
