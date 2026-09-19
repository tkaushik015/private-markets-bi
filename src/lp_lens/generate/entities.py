"""Managers, funds, investors and commitments: the entities the cash flow engine hangs off.

All four are drawn in a fixed order from their own random streams, so the set of managers does not
change when the number of funds does.
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass

import numpy as np

from .config import GeneratorConfig
from .names import INVESTOR_STEMS, MANAGER_STEMS, MANAGER_SUFFIXES, investor_name, roman, strategy_label


def money(value: float) -> float:
    """Round an amount to cents. Applied at the point a figure becomes an output, never mid-sum."""
    return round(float(value), 2)


def add_years(date: dt.date, years: int) -> dt.date:
    """Add whole years, clamping the day to the target month's length.

    The clamp matters: management fees fall on commitment anniversaries, and a commitment signed
    on 29 February has no anniversary in a non-leap year. Clamping to the 28th keeps the schedule
    annual instead of raising, and keeps it deterministic instead of drifting the way repeated
    365-day additions would.
    """
    year = date.year + years
    day = min(date.day, calendar.monthrange(year, date.month)[1])
    return dt.date(year, date.month, day)


@dataclass(frozen=True)
class Manager:
    manager_id: str
    name: str
    hq_region: str
    founded_year: int


@dataclass(frozen=True)
class Fund:
    fund_id: str
    manager_id: str
    fund_name: str
    strategy: str
    vintage_year: int
    currency: str
    fund_size: float
    geography_focus: str
    # Below this line: generator ground truth, deliberately not written to Parquet. Publishing the
    # target multiple would let a model read the answer off the raw layer instead of computing it,
    # and the tests are stronger for having to derive realised TVPI from the cash flows and NAV.
    life_years: int
    terminal_tvpi: float

    @property
    def vintage_start(self) -> dt.date:
        return dt.date(self.vintage_year, 1, 1)

    @property
    def liquidation_date(self) -> dt.date:
        """The fund's final quarter end, after which it holds nothing.

        Deliberately a quarter end rather than the vintage-start anniversary. Anniversaries fall on
        1 January, which is not a quarter-end date, so a NAV grid truncated at one would stop at the
        previous 31 December and never coincide with liquidation — leaving the final NAV at whatever
        the J-curve happened to evaluate to instead of the zero a wound-up fund must report. A fund
        with a 8-year life and a 2012 vintage therefore ends on 2019-12-31.
        """
        return dt.date(self.vintage_year + self.life_years - 1, 12, 31)


@dataclass(frozen=True)
class Investor:
    investor_id: str
    name: str
    investor_type: str


@dataclass(frozen=True)
class Commitment:
    commitment_id: str
    investor_id: str
    fund_id: str
    commitment_amount: float
    commitment_date: dt.date


def build_managers(config: GeneratorConfig, rng: np.random.Generator) -> list[Manager]:
    cfg = config.managers
    if cfg.count > len(MANAGER_STEMS):
        raise ValueError(
            f"cannot name {cfg.count} managers from {len(MANAGER_STEMS)} unique stems; "
            "add more entries to names.MANAGER_STEMS"
        )
    stems = rng.choice(np.array(MANAGER_STEMS), size=cfg.count, replace=False)
    lo, hi = cfg.founded_year_range
    managers = []
    for i, stem in enumerate(stems, start=1):
        suffix = MANAGER_SUFFIXES[int(rng.integers(0, len(MANAGER_SUFFIXES)))]
        managers.append(
            Manager(
                manager_id=f"MGR{i:04d}",
                name=f"{stem} {suffix}",
                hq_region=cfg.hq_regions[int(rng.integers(0, len(cfg.hq_regions)))],
                founded_year=int(rng.integers(lo, hi + 1)),
            )
        )
    return managers


def build_funds(config: GeneratorConfig, managers: list[Manager], rng: np.random.Generator) -> list[Fund]:
    cfg = config.funds
    strategy_names = tuple(cfg.strategies)  # dict order is the YAML order, which is stable
    weights = np.array([cfg.strategies[s].weight for s in strategy_names], dtype=float)
    weights = weights / weights.sum()

    # Every manager gets at least one fund before any manager gets a second, so the manager
    # dimension has no orphan rows. Beyond that, allocation is random and some managers end up
    # with several funds, which is what a real universe looks like.
    manager_ids = [m.manager_id for m in managers]
    assigned: list[str] = []
    for i in range(cfg.count):
        if i < len(manager_ids):
            assigned.append(manager_ids[i])
        else:
            assigned.append(manager_ids[int(rng.integers(0, len(manager_ids)))])

    stem_by_manager = {m.manager_id: m.name.rsplit(" ", 1)[0] for m in managers}
    # A manager's Buyout funds number I, II, III... independently of its Credit funds.
    sequence: dict[tuple[str, str], int] = {}

    vintage_lo, vintage_hi = cfg.vintage_year_range
    size_lo, size_hi = cfg.size_range_musd

    funds = []
    for i in range(cfg.count):
        manager_id = assigned[i]
        strategy = strategy_names[int(rng.choice(len(strategy_names), p=weights))]
        key = (manager_id, strategy)
        sequence[key] = sequence.get(key, 0) + 1
        params = cfg.strategies[strategy]
        life_lo, life_hi = params.life_years_range
        stem = stem_by_manager[manager_id]
        funds.append(
            Fund(
                fund_id=f"FUND{i + 1:04d}",
                manager_id=manager_id,
                fund_name=f"{stem} {strategy_label(strategy)} {roman(sequence[key])}",
                strategy=strategy,
                vintage_year=int(rng.integers(vintage_lo, vintage_hi + 1)),
                currency="EUR" if rng.random() < cfg.eur_share else "USD",
                fund_size=money(rng.uniform(size_lo, size_hi) * 1_000_000.0),
                geography_focus=cfg.geography_focus[int(rng.integers(0, len(cfg.geography_focus)))],
                life_years=int(rng.integers(life_lo, life_hi + 1)),
                terminal_tvpi=float(np.exp(rng.normal(params.tvpi_log_mean, params.tvpi_log_sd))),
            )
        )
    return funds


def build_investors(config: GeneratorConfig, rng: np.random.Generator) -> list[Investor]:
    cfg = config.investors
    if cfg.count > len(INVESTOR_STEMS):
        raise ValueError(
            f"cannot name {cfg.count} investors from {len(INVESTOR_STEMS)} unique stems; "
            "add more entries to names.INVESTOR_STEMS"
        )
    stems = rng.choice(np.array(INVESTOR_STEMS), size=cfg.count, replace=False)
    investors = []
    for i, stem in enumerate(stems, start=1):
        investor_type = cfg.types[int(rng.integers(0, len(cfg.types)))]
        investors.append(
            Investor(
                investor_id=f"LP{i:03d}",
                name=investor_name(str(stem), investor_type),
                investor_type=investor_type,
            )
        )
    return investors


def build_commitments(
    config: GeneratorConfig,
    funds: list[Fund],
    investors: list[Investor],
    rng: np.random.Generator,
) -> list[Commitment]:
    cfg = config.commitments
    fund_by_id = {f.fund_id: f for f in funds}
    fund_ids = np.array([f.fund_id for f in funds])
    count_lo, count_hi = cfg.funds_per_investor_range
    frac_lo, frac_hi = cfg.fraction_of_fund_size_range
    lag_lo, lag_hi = cfg.date_lag_days_range

    commitments = []
    for investor in investors:
        n = int(rng.integers(count_lo, count_hi + 1))
        chosen = sorted(str(x) for x in rng.choice(fund_ids, size=n, replace=False))
        for fund_id in chosen:
            fund = fund_by_id[fund_id]
            lag = int(rng.integers(lag_lo, lag_hi + 1))
            commitment_date = fund.vintage_start + dt.timedelta(days=lag)
            # Safety net rather than a live code path: with the shipped config the latest vintage
            # plus the longest lag still falls well before the as-of date. It exists so that
            # widening vintage_year_range cannot silently emit a commitment after the as-of date.
            commitment_date = min(commitment_date, config.as_of_date)
            commitments.append(
                Commitment(
                    commitment_id=f"CMT{len(commitments) + 1:05d}",
                    investor_id=investor.investor_id,
                    fund_id=fund_id,
                    commitment_amount=money(fund.fund_size * rng.uniform(frac_lo, frac_hi)),
                    commitment_date=commitment_date,
                )
            )
    return commitments
