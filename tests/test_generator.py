"""Tests for the synthetic private markets data generator.

Two groups. The determinism tests write Parquet to a temp directory and compare file hashes,
because byte-reproducibility is a property of the written file and cannot be checked in memory.
Everything else asserts on the in-memory DataFrames, which keeps the suite fast and tests the data
rather than the serialiser.

The dataset is generated once per session. Generation is pure, so sharing it across tests cannot
leak state between them, and regenerating it per test would multiply the runtime for no gain.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from lp_lens.generate import (
    DISTRIBUTION_TYPES,
    FLOW_DIRECTION,
    FLOW_TYPES,
    PAID_IN_TYPES,
    TABLE_ORDER,
    GeneratorConfig,
    file_hashes,
    generate_dataset,
    load_config,
    write_dataset,
)
from lp_lens.generate.__main__ import main as generate_cli
from lp_lens.generate.entities import build_funds, build_managers
from lp_lens.generate.market import daily_dates
from lp_lens.generate.streams import make_streams

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "generator.yaml"

QUARTER_END_MONTH_DAY = {(3, 31), (6, 30), (9, 30), (12, 31)}

# Primary key of each table, asserted unique and not null below.
PRIMARY_KEYS: dict[str, list[str]] = {
    "managers": ["manager_id"],
    "funds": ["fund_id"],
    "investors": ["investor_id"],
    "commitments": ["commitment_id"],
    "cash_flows": ["cash_flow_id"],
    "nav": ["fund_id", "investor_id", "quarter_end"],
    "fx_rates": ["rate_date", "from_currency", "to_currency"],
    "public_index": ["index_date", "index_name"],
}


@pytest.fixture(scope="session")
def config() -> GeneratorConfig:
    return load_config(CONFIG_PATH)


@pytest.fixture(scope="session")
def dataset(config: GeneratorConfig) -> dict[str, pd.DataFrame]:
    return generate_dataset(config)


@pytest.fixture(scope="session")
def commitment_amounts(dataset: dict[str, pd.DataFrame]) -> dict[tuple[str, str], float]:
    cm = dataset["commitments"]
    return {(f, i): a for f, i, a in zip(cm.fund_id, cm.investor_id, cm.commitment_amount, strict=True)}


# --------------------------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------------------------


def test_same_seed_and_config_produce_byte_identical_parquet(config: GeneratorConfig, tmp_path: Path) -> None:
    first, second = tmp_path / "run1", tmp_path / "run2"
    write_dataset(generate_dataset(config), first)
    write_dataset(generate_dataset(config), second)
    assert file_hashes(first) == file_hashes(second)


def test_different_seed_changes_every_table(config: GeneratorConfig, tmp_path: Path) -> None:
    other = config.model_copy(update={"seed": config.seed + 1})
    base, changed = tmp_path / "base", tmp_path / "changed"
    write_dataset(generate_dataset(config), base)
    write_dataset(generate_dataset(other), changed)

    base_hashes, changed_hashes = file_hashes(base), file_hashes(changed)
    unchanged = [name for name in TABLE_ORDER if base_hashes[name] == changed_hashes[name]]
    assert not unchanged, f"these tables did not respond to the seed: {unchanged}"


def test_generate_dataset_is_pure(config: GeneratorConfig, dataset: dict[str, pd.DataFrame]) -> None:
    """A second in-memory run must equal the first, with no reliance on the filesystem."""
    again = generate_dataset(config)
    for name in TABLE_ORDER:
        pd.testing.assert_frame_equal(dataset[name], again[name], check_exact=True)


# --------------------------------------------------------------------------------------------
# Constraints
# --------------------------------------------------------------------------------------------


def test_cumulative_paid_in_never_exceeds_commitment_plus_recallable(
    dataset: dict[str, pd.DataFrame], commitment_amounts: dict[tuple[str, str], float]
) -> None:
    """The headline invariant: an LP cannot be drawn more than it committed, plus what it has
    already had returned as recallable. Checked cumulatively at every flow, not just at the end,
    because a mid-life breach that a later distribution masks is still a breach."""
    cf = dataset["cash_flows"].sort_values(["fund_id", "investor_id", "flow_date"])
    breaches = []
    for (fund_id, investor_id), group in cf.groupby(["fund_id", "investor_id"], sort=True):
        commitment = commitment_amounts[(fund_id, investor_id)]
        paid_in = recallable = 0.0
        for flow_type, amount in zip(group.flow_type, group.amount, strict=True):
            if flow_type in PAID_IN_TYPES:
                paid_in += amount
                if paid_in > commitment + recallable + 0.01:
                    breaches.append((fund_id, investor_id, paid_in, commitment + recallable))
            elif flow_type == "recallable_distribution":
                recallable += amount
    assert not breaches, f"{len(breaches)} paid-in breaches, first: {breaches[:1]}"


def test_nav_is_never_negative(dataset: dict[str, pd.DataFrame]) -> None:
    nav = dataset["nav"]
    assert (nav.nav >= 0).all(), f"{int((nav.nav < 0).sum())} negative NAV rows"


def test_all_amounts_are_positive(dataset: dict[str, pd.DataFrame]) -> None:
    """Amounts are unsigned magnitudes; direction lives in flow_type, so a zero or negative
    amount would mean the sign convention had been broken."""
    amount = dataset["cash_flows"].amount
    assert (amount > 0).all(), f"{int((amount <= 0).sum())} non-positive amounts"


def test_every_flow_type_has_a_documented_direction(dataset: dict[str, pd.DataFrame]) -> None:
    assert set(dataset["cash_flows"].flow_type) <= set(FLOW_TYPES)
    assert set(FLOW_DIRECTION) == set(FLOW_TYPES)
    assert PAID_IN_TYPES | DISTRIBUTION_TYPES == set(FLOW_TYPES)
    assert not PAID_IN_TYPES & DISTRIBUTION_TYPES
    assert all(FLOW_DIRECTION[t] == -1 for t in PAID_IN_TYPES)
    assert all(FLOW_DIRECTION[t] == +1 for t in DISTRIBUTION_TYPES)


def test_no_cash_flow_precedes_its_commitment_date(dataset: dict[str, pd.DataFrame]) -> None:
    merged = dataset["cash_flows"].merge(
        dataset["commitments"][["fund_id", "investor_id", "commitment_date"]],
        on=["fund_id", "investor_id"],
        how="left",
    )
    assert merged.commitment_date.notna().all(), "a cash flow has no matching commitment"
    early = merged[merged.flow_date < merged.commitment_date]
    assert early.empty, f"{len(early)} cash flows precede their commitment date"


def test_nothing_is_generated_after_the_as_of_date(config: GeneratorConfig, dataset: dict[str, pd.DataFrame]) -> None:
    as_of = config.as_of_date
    assert (dataset["cash_flows"].flow_date <= as_of).all(), "cash flow after the as-of date"
    assert (dataset["nav"].quarter_end <= as_of).all(), "NAV after the as-of date"
    assert (dataset["commitments"].commitment_date <= as_of).all(), "commitment after the as-of date"
    assert (dataset["fx_rates"].rate_date <= as_of).all(), "FX rate after the as-of date"
    assert (dataset["public_index"].index_date <= as_of).all(), "index level after the as-of date"


@pytest.mark.parametrize(
    ("child", "child_key", "parent", "parent_key"),
    [
        ("funds", "manager_id", "managers", "manager_id"),
        ("commitments", "fund_id", "funds", "fund_id"),
        ("commitments", "investor_id", "investors", "investor_id"),
    ],
)
def test_single_column_foreign_keys_resolve(
    dataset: dict[str, pd.DataFrame], child: str, child_key: str, parent: str, parent_key: str
) -> None:
    orphans = set(dataset[child][child_key]) - set(dataset[parent][parent_key])
    assert not orphans, f"{child}.{child_key} has values absent from {parent}.{parent_key}: {sorted(orphans)[:5]}"


@pytest.mark.parametrize("table", ["cash_flows", "nav"])
def test_fact_tables_resolve_to_a_commitment_pair(dataset: dict[str, pd.DataFrame], table: str) -> None:
    """cash_flows and nav are both grained on (fund, investor), which must be a pair that
    actually committed. A fact against a fund an investor never committed to is unattributable."""
    cm = dataset["commitments"]
    pairs = set(zip(cm.fund_id, cm.investor_id, strict=True))
    frame = dataset[table]
    orphans = set(zip(frame.fund_id, frame.investor_id, strict=True)) - pairs
    assert not orphans, f"{table} has {len(orphans)} (fund, investor) pairs with no commitment"


@pytest.mark.parametrize("table", sorted(PRIMARY_KEYS))
def test_primary_key_is_unique_and_not_null(dataset: dict[str, pd.DataFrame], table: str) -> None:
    keys = PRIMARY_KEYS[table]
    frame = dataset[table]
    assert not frame[keys].isna().any().any(), f"{table} has nulls in {keys}"
    duplicated = frame.duplicated(subset=keys)
    assert not duplicated.any(), f"{table} has {int(duplicated.sum())} duplicate rows on {keys}"


def test_quarter_end_values_are_real_quarter_ends(dataset: dict[str, pd.DataFrame]) -> None:
    offenders = {q for q in dataset["nav"].quarter_end if (q.month, q.day) not in QUARTER_END_MONTH_DAY}
    assert not offenders, f"not quarter-end dates: {sorted(offenders)[:5]}"


def test_no_nav_before_the_first_capital_call(dataset: dict[str, pd.DataFrame]) -> None:
    calls = dataset["cash_flows"]
    calls = calls[calls.flow_type == "capital_call"]
    first_call = calls.groupby(["fund_id", "investor_id"]).flow_date.min()
    first_nav = dataset["nav"].groupby(["fund_id", "investor_id"]).quarter_end.min()
    joined = pd.DataFrame({"first_call": first_call, "first_nav": first_nav}).dropna()
    assert not joined.empty, "no (fund, investor) pair has both a call and a NAV"
    early = joined[joined.first_nav < joined.first_call]
    assert early.empty, f"{len(early)} pairs carry NAV before their first capital call"


def test_nav_stops_at_liquidation_with_a_zero_final_value(
    config: GeneratorConfig, dataset: dict[str, pd.DataFrame]
) -> None:
    """A NAV series can only end early because the fund liquidated, and a liquidated fund holds
    nothing. So any series whose last quarter is before the as-of quarter must end at zero; a
    non-zero final NAV would mean value vanished without being distributed."""
    nav = dataset["nav"]
    last_quarter = max(q for q in nav.quarter_end if q <= config.as_of_date)
    final = nav.sort_values("quarter_end").groupby(["fund_id", "investor_id"]).tail(1)
    ended_early = final[final.quarter_end < last_quarter]
    assert not ended_early.empty, "no fund liquidated before the as-of date, so this proves nothing"
    non_zero = ended_early[ended_early.nav != 0.0]
    assert non_zero.empty, f"{len(non_zero)} liquidated pairs carry a non-zero final NAV"


def test_fx_rates_cover_every_eur_flow_and_nav_date(dataset: dict[str, pd.DataFrame]) -> None:
    cf, nav = dataset["cash_flows"], dataset["nav"]
    needed = set(cf[cf.currency == "EUR"].flow_date) | set(nav[nav.currency == "EUR"].quarter_end)
    assert needed, "no EUR-denominated rows exist, so this test proves nothing"
    missing = needed - set(dataset["fx_rates"].rate_date)
    assert not missing, f"{len(missing)} EUR dates have no FX rate, e.g. {sorted(missing)[:5]}"


# --------------------------------------------------------------------------------------------
# Row counts, ranges and categorical values
# --------------------------------------------------------------------------------------------


def test_entity_row_counts_match_config(config: GeneratorConfig, dataset: dict[str, pd.DataFrame]) -> None:
    assert len(dataset["managers"]) == config.managers.count
    assert len(dataset["funds"]) == config.funds.count
    assert len(dataset["investors"]) == config.investors.count


def test_commitments_per_investor_within_configured_range(
    config: GeneratorConfig, dataset: dict[str, pd.DataFrame]
) -> None:
    lo, hi = config.commitments.funds_per_investor_range
    per_investor = dataset["commitments"].groupby("investor_id").size()
    assert len(per_investor) == config.investors.count, "an investor committed to nothing"
    assert per_investor.min() >= lo, f"an investor holds {per_investor.min()} commitments, below {lo}"
    assert per_investor.max() <= hi, f"an investor holds {per_investor.max()} commitments, above {hi}"


def test_no_investor_commits_to_the_same_fund_twice(dataset: dict[str, pd.DataFrame]) -> None:
    cm = dataset["commitments"]
    duplicated = cm.duplicated(subset=["investor_id", "fund_id"])
    assert not duplicated.any(), f"{int(duplicated.sum())} repeated investor/fund commitments"


def test_vintage_years_within_configured_range(config: GeneratorConfig, dataset: dict[str, pd.DataFrame]) -> None:
    lo, hi = config.funds.vintage_year_range
    vintages = dataset["funds"].vintage_year
    assert vintages.min() >= lo and vintages.max() <= hi


def test_categorical_values_come_from_the_config(config: GeneratorConfig, dataset: dict[str, pd.DataFrame]) -> None:
    checks = [
        (set(dataset["funds"].strategy), set(config.funds.strategies), "fund strategy"),
        (set(dataset["funds"].currency), {"USD", "EUR"}, "fund currency"),
        (set(dataset["funds"].geography_focus), set(config.funds.geography_focus), "geography focus"),
        (set(dataset["managers"].hq_region), set(config.managers.hq_regions), "manager hq region"),
        (set(dataset["investors"].investor_type), set(config.investors.types), "investor type"),
        (set(dataset["cash_flows"].flow_type), set(FLOW_TYPES), "flow type"),
        (set(dataset["public_index"].index_name), {config.market.index.name}, "index name"),
    ]
    for actual, allowed, label in checks:
        assert actual <= allowed, f"{label} has values outside the config: {sorted(actual - allowed)}"


def test_fund_sizes_and_commitments_within_configured_bounds(
    config: GeneratorConfig, dataset: dict[str, pd.DataFrame]
) -> None:
    size_lo, size_hi = config.funds.size_range_musd
    sizes = dataset["funds"].fund_size
    assert sizes.min() >= size_lo * 1_000_000.0 - 0.01
    assert sizes.max() <= size_hi * 1_000_000.0 + 0.01

    frac_lo, frac_hi = config.commitments.fraction_of_fund_size_range
    merged = dataset["commitments"].merge(dataset["funds"][["fund_id", "fund_size"]], on="fund_id")
    fraction = merged.commitment_amount / merged.fund_size
    assert fraction.min() >= frac_lo - 1e-9
    assert fraction.max() <= frac_hi + 1e-9


@pytest.mark.parametrize(("table", "date_column"), [("fx_rates", "rate_date"), ("public_index", "index_date")])
def test_market_series_cover_every_calendar_day(
    config: GeneratorConfig, dataset: dict[str, pd.DataFrame], table: str, date_column: str
) -> None:
    expected = daily_dates(config.history_start, config.as_of_date)
    actual = list(dataset[table][date_column])
    assert actual == expected, f"{table} is not a complete daily series"


def test_market_series_stay_in_a_plausible_range(dataset: dict[str, pd.DataFrame]) -> None:
    """Not a tight distributional claim, just a guard: mean reversion on FX and a positive drift
    on the index should not produce a rate near zero or an index that collapses."""
    rate = dataset["fx_rates"].rate
    assert rate.min() > 0.5 and rate.max() < 2.0, f"EUR/USD left a plausible band: {rate.min()}-{rate.max()}"
    level = dataset["public_index"].level
    assert level.min() > 0.0, "index level went non-positive"


# --------------------------------------------------------------------------------------------
# The outcome model
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fund_performance(dataset: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Realised TVPI and DPI per fund at the as-of date, derived the way a consumer would."""
    cf = dataset["cash_flows"]
    paid_in = cf[cf.flow_type.isin(PAID_IN_TYPES)].groupby("fund_id").amount.sum()
    distributed = cf[cf.flow_type.isin(DISTRIBUTION_TYPES)].groupby("fund_id").amount.sum()
    latest_nav = (
        dataset["nav"]
        .sort_values("quarter_end")
        .groupby(["fund_id", "investor_id"])
        .tail(1)
        .groupby("fund_id")
        .nav.sum()
    )
    frame = pd.DataFrame({"paid_in": paid_in})
    frame["distributed"] = distributed.reindex(frame.index).fillna(0.0)
    frame["nav"] = latest_nav.reindex(frame.index).fillna(0.0)
    frame["tvpi"] = (frame.distributed + frame.nav) / frame.paid_in
    frame["dpi"] = frame.distributed / frame.paid_in
    return frame.join(dataset["funds"].set_index("fund_id")[["strategy", "vintage_year"]])


def test_outcomes_span_loss_making_to_strong(fund_performance: pd.DataFrame) -> None:
    """The point of a spread of outcomes is that both tails exist. A generator that produced only
    winners would make every downstream metric look good and test nothing."""
    assert (fund_performance.tvpi < 1.0).any(), "no fund is below 1.0x; there is no downside in the data"
    assert (fund_performance.tvpi > 2.0).any(), "no fund is above 2.0x; there is no upside in the data"


def test_strategy_dispersion_is_ordered_as_configured(config: GeneratorConfig, fund_performance: pd.DataFrame) -> None:
    """The most and least dispersed strategies in the config should be the most and least
    dispersed in the realised data too. Read off the config rather than hard-coded, so
    recalibrating the strategies cannot leave this test asserting a stale ordering."""
    sds = {name: params.tvpi_log_sd for name, params in config.funds.strategies.items()}
    widest, narrowest = max(sds, key=sds.__getitem__), min(sds, key=sds.__getitem__)
    spread = fund_performance.groupby("strategy").tvpi.agg(lambda s: s.max() - s.min())
    assert spread[widest] > spread[narrowest], (
        f"{widest} (configured sd {sds[widest]}) realised a spread of {spread[widest]:.2f}, "
        f"not wider than {narrowest} (sd {sds[narrowest]}) at {spread[narrowest]:.2f}"
    )


def test_j_curve_starts_below_one_and_recovers(fund_performance: pd.DataFrame) -> None:
    """Young funds should sit below 1.0x because fees are drawn before value accrues, and mature
    funds should have recovered. That is the J-curve, tested on the data rather than the model."""
    young = fund_performance[fund_performance.vintage_year >= 2023]
    mature = fund_performance[fund_performance.vintage_year <= 2014]
    assert not young.empty and not mature.empty, "need both young and mature vintages to test the J-curve"
    assert young.tvpi.median() < 1.0, f"young vintages median TVPI {young.tvpi.median():.2f} is not below 1.0"
    assert mature.tvpi.median() > young.tvpi.median(), "mature vintages did not recover above young ones"


def test_distributions_only_begin_after_the_configured_year(
    config: GeneratorConfig, dataset: dict[str, pd.DataFrame]
) -> None:
    """Calls are front-loaded and distributions back-loaded. The observable form of that is no
    distribution landing before the configured start year of the fund's life."""
    cf = dataset["cash_flows"]
    merged = cf[cf.flow_type.isin(DISTRIBUTION_TYPES)].merge(
        dataset["funds"][["fund_id", "vintage_year"]], on="fund_id"
    )
    earliest_allowed = merged.vintage_year + config.cash_flows.distribution_start_year
    actual_year = merged.flow_date.map(lambda d: d.year)
    assert (actual_year >= earliest_allowed).all(), "a distribution landed before the configured start year"


def test_capital_calls_are_front_loaded(dataset: dict[str, pd.DataFrame]) -> None:
    """More than half of called capital should land in the first half of the call window."""
    cf = dataset["cash_flows"]
    calls = cf[cf.flow_type == "capital_call"].merge(dataset["funds"][["fund_id", "vintage_year"]], on="fund_id")
    years_in = calls.flow_date.map(lambda d: d.year) - calls.vintage_year
    early_share = calls.amount[years_in <= 2].sum() / calls.amount.sum()
    assert early_share > 0.5, f"only {early_share:.0%} of called capital lands in the first three years"


# --------------------------------------------------------------------------------------------
# Per-strategy terminal outcome distributions
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def modelled_terminal_tvpi(config: GeneratorConfig) -> pd.DataFrame:
    """Terminal TVPI per fund, read off the generator's own model.

    This is the one place the tests reach into the entity builders rather than the published
    output, and it needs justifying. `terminal_tvpi` is deliberately absent from the Parquet, and
    for a fund still mid-life there is no observable in the output that stands in for its terminal
    multiple -- realised TVPI at the as-of date is a function of fund age as much as of fund
    quality. Since the claim under test is about the configured outcome distribution itself, the
    model is the right thing to measure.

    `test_liquidated_funds_realise_their_modelled_terminal_tvpi` is what makes this legitimate: it
    shows that wherever the output *can* be compared, it agrees with the model.
    """
    streams = make_streams(config.seed)
    managers = build_managers(config, streams["managers"])
    funds = build_funds(config, managers, streams["funds"])
    return pd.DataFrame(
        [
            {
                "fund_id": fund.fund_id,
                "strategy": fund.strategy,
                "terminal_tvpi": fund.terminal_tvpi,
                "liquidated": fund.liquidation_date <= config.as_of_date,
            }
            for fund in funds
        ]
    )


def test_liquidated_funds_realise_their_modelled_terminal_tvpi(
    modelled_terminal_tvpi: pd.DataFrame, fund_performance: pd.DataFrame
) -> None:
    """For a fully liquidated fund, realised TVPI must equal the modelled terminal multiple.

    Nothing is left to value, so distributions over paid-in is the final answer, and it should
    close on the number the model drew. This is both a check that the lifecycle arithmetic closes
    and the warrant for using modelled terminal TVPI in the tests below.
    """
    joined = modelled_terminal_tvpi.set_index("fund_id").join(fund_performance[["tvpi"]], how="inner")
    liquidated = joined[joined.liquidated]
    assert not liquidated.empty, "no liquidated fund carries commitments, so this proves nothing"
    error = ((liquidated.tvpi - liquidated.terminal_tvpi) / liquidated.terminal_tvpi).abs()
    assert error.max() < 1e-6, (
        f"realised TVPI diverged from the model by up to {error.max():.2e} across {len(liquidated)} liquidated funds"
    )


def test_every_strategy_is_centred_above_break_even(modelled_terminal_tvpi: pd.DataFrame) -> None:
    """Each strategy's median terminal TVPI must exceed 1.0x.

    A strategy centred at break-even makes its whole cohort indistinguishable from a fund that
    merely returned capital, which leaves the downstream metrics nothing to separate.
    """
    medians = modelled_terminal_tvpi.groupby("strategy").terminal_tvpi.median()
    assert len(medians) == len(set(modelled_terminal_tvpi.strategy)), "a strategy vanished"
    below = medians[medians <= 1.0]
    assert below.empty, f"strategies centred at or below break-even: {below.round(3).to_dict()}"


def test_venture_has_the_widest_terminal_spread(config: GeneratorConfig, modelled_terminal_tvpi: pd.DataFrame) -> None:
    """Venture must be the most dispersed strategy in the drawn data, not just in the config.

    Dispersion is measured as the sample standard deviation of log terminal TVPI, which estimates
    the configured `tvpi_log_sd` directly and is comparable across strategies with different fund
    counts. A raw max-minus-min range would not be: it grows with sample size, so the 22 buyout
    funds would be flattered against the 4 infrastructure ones.
    """
    log_sd = modelled_terminal_tvpi.groupby("strategy").terminal_tvpi.agg(lambda s: float(np.log(s).std(ddof=1)))
    widest = log_sd.idxmax()
    assert widest == "Venture", f"{widest} dispersed more than venture: {log_sd.round(3).to_dict()}"
    assert log_sd["Venture"] == pytest.approx(config.funds.strategies["Venture"].tvpi_log_sd, abs=0.35), (
        f"venture's drawn dispersion {log_sd['Venture']:.3f} is far from its configured sd"
    )


def test_credit_and_infrastructure_are_the_narrowest_and_stay_above_break_even(
    modelled_terminal_tvpi: pd.DataFrame,
) -> None:
    """The two deliberately tight strategies should be the two least dispersed, and tight enough
    around a positive centre that no fund in either lands below break-even. That combination --
    narrow band and positive centre together -- is the point of how they are calibrated."""
    log_sd = modelled_terminal_tvpi.groupby("strategy").terminal_tvpi.agg(lambda s: float(np.log(s).std(ddof=1)))
    narrowest_two = set(log_sd.nsmallest(2).index)
    assert narrowest_two == {"Private Credit", "Infrastructure"}, (
        f"expected credit and infrastructure to be the tightest, got {sorted(narrowest_two)}: "
        f"{log_sd.round(3).to_dict()}"
    )

    tight = modelled_terminal_tvpi[modelled_terminal_tvpi.strategy.isin({"Private Credit", "Infrastructure"})]
    below = tight[tight.terminal_tvpi < 1.0]
    assert below.empty, f"{len(below)} credit/infrastructure funds are modelled below break-even"


def test_wide_strategies_still_carry_a_loss_making_tail(modelled_terminal_tvpi: pd.DataFrame) -> None:
    """Raising every strategy's centre above 1.0x must not remove the downside from the book.
    The dispersed strategies are where it has to live."""
    wide = modelled_terminal_tvpi[modelled_terminal_tvpi.strategy.isin({"Venture", "Growth", "Buyout"})]
    assert (wide.terminal_tvpi < 1.0).any(), "no fund in the dispersed strategies is modelled below 1.0x"
    assert (modelled_terminal_tvpi.terminal_tvpi > 3.0).any(), "no fund is modelled above 3.0x"


# --------------------------------------------------------------------------------------------
# Config and CLI
# --------------------------------------------------------------------------------------------


def test_config_rejects_an_unknown_key(tmp_path: Path) -> None:
    """extra="forbid" throughout, so a typo fails at load rather than falling back to a default."""
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["managers"]["hq_reigons"] = ["Typo"]
    path = tmp_path / "typo.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(path)


def test_config_rejects_paid_in_fraction_above_one(tmp_path: Path) -> None:
    """Paid-in above commitment is only legitimate against recallable distributions already
    received, which the call schedule cannot know about when it is sized."""
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["cash_flows"]["terminal_paid_in_fraction_range"] = [0.9, 1.4]
    path = tmp_path / "overdrawn.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(path)


def test_cli_writes_every_table(tmp_path: Path) -> None:
    exit_code = generate_cli(["--config", str(CONFIG_PATH), "--out", str(tmp_path)])
    assert exit_code == 0
    for name in TABLE_ORDER:
        path = tmp_path / f"{name}.parquet"
        assert path.is_file(), f"{name}.parquet was not written"
        assert path.stat().st_size > 0, f"{name}.parquet is empty"


def test_written_parquet_round_trips_with_expected_types(config: GeneratorConfig, tmp_path: Path) -> None:
    write_dataset(generate_dataset(config), tmp_path)
    nav = pd.read_parquet(tmp_path / "nav.parquet")
    assert list(nav.columns) == ["fund_id", "investor_id", "quarter_end", "nav", "currency"]
    assert isinstance(nav.quarter_end.iloc[0], dt.date), "quarter_end did not round-trip as a date"
    assert nav.nav.dtype.kind == "f", "nav did not round-trip as a float"
