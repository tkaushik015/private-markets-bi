"""Typed configuration for the synthetic data generator.

Every knob the generator reads lives here, and every field is validated on load. Nothing in the
generator reads an environment variable or a literal constant that is not either in this file or
derived from it, so a config file plus the code is a complete description of the output.

`extra="forbid"` throughout: a typo in the YAML fails loudly at load time rather than silently
falling back to a default and producing data that does not match what the file appears to say.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Fraction = Annotated[float, Field(ge=0.0, le=1.0)]
Positive = Annotated[float, Field(gt=0.0)]


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StrategyParams(Base):
    """Per-strategy outcome distribution.

    Terminal TVPI is drawn as exp(Normal(tvpi_log_mean, tvpi_log_sd)), so tvpi_log_mean is the log
    of the median multiple and tvpi_log_sd sets the dispersion. Venture carries a much larger sd
    than private credit on purpose: the spread of outcomes across strategies is the point, and a
    wide sd is what puts both loss-making and top-quartile funds in the same strategy.
    """

    weight: Positive
    tvpi_log_mean: float
    tvpi_log_sd: Positive
    life_years_range: tuple[int, int]

    @model_validator(mode="after")
    def _check_life(self) -> StrategyParams:
        lo, hi = self.life_years_range
        if not 1 <= lo <= hi:
            raise ValueError(f"life_years_range must satisfy 1 <= lo <= hi, got {self.life_years_range}")
        return self


class ManagerConfig(Base):
    count: int = Field(gt=0)
    hq_regions: tuple[str, ...]
    founded_year_range: tuple[int, int]

    @model_validator(mode="after")
    def _check(self) -> ManagerConfig:
        lo, hi = self.founded_year_range
        if lo > hi:
            raise ValueError(f"founded_year_range must be ordered, got {self.founded_year_range}")
        if not self.hq_regions:
            raise ValueError("hq_regions must not be empty")
        return self


class FundConfig(Base):
    count: int = Field(gt=0)
    vintage_year_range: tuple[int, int]
    eur_share: Fraction
    geography_focus: tuple[str, ...]
    size_range_musd: tuple[Positive, Positive]
    strategies: dict[str, StrategyParams]

    @model_validator(mode="after")
    def _check(self) -> FundConfig:
        lo, hi = self.vintage_year_range
        if lo > hi:
            raise ValueError(f"vintage_year_range must be ordered, got {self.vintage_year_range}")
        if self.size_range_musd[0] > self.size_range_musd[1]:
            raise ValueError(f"size_range_musd must be ordered, got {self.size_range_musd}")
        if not self.strategies:
            raise ValueError("at least one strategy must be configured")
        if not self.geography_focus:
            raise ValueError("geography_focus must not be empty")
        return self


class InvestorConfig(Base):
    count: int = Field(gt=0)
    types: tuple[str, ...]

    @model_validator(mode="after")
    def _check(self) -> InvestorConfig:
        if not self.types:
            raise ValueError("investor types must not be empty")
        return self


class CommitmentConfig(Base):
    funds_per_investor_range: tuple[int, int]
    fraction_of_fund_size_range: tuple[Positive, Positive]
    date_lag_days_range: tuple[int, int]

    @model_validator(mode="after")
    def _check(self) -> CommitmentConfig:
        lo, hi = self.funds_per_investor_range
        if not 1 <= lo <= hi:
            raise ValueError(
                f"funds_per_investor_range must satisfy 1 <= lo <= hi, got {self.funds_per_investor_range}"
            )
        if self.fraction_of_fund_size_range[0] > self.fraction_of_fund_size_range[1]:
            raise ValueError("fraction_of_fund_size_range must be ordered")
        lag_lo, lag_hi = self.date_lag_days_range
        if not 0 <= lag_lo <= lag_hi:
            raise ValueError(f"date_lag_days_range must satisfy 0 <= lo <= hi, got {self.date_lag_days_range}")
        return self


class CashFlowConfig(Base):
    """Shape of the call and distribution schedules.

    call_beta and distribution_beta are the (a, b) parameters of a Beta draw over each window.
    a < b skews early, a > b skews late, which is how "calls front-loaded, distributions
    back-loaded" is expressed without hard-coding a year-by-year table.
    """

    call_period_years: int = Field(gt=0)
    calls_per_commitment_range: tuple[int, int]
    call_beta: tuple[Positive, Positive]
    distribution_start_year: int = Field(gt=0)
    distribution_end_year: int = Field(gt=0)
    distributions_per_commitment_range: tuple[int, int]
    distribution_beta: tuple[Positive, Positive]
    terminal_paid_in_fraction_range: tuple[Positive, Positive]
    management_fee_rate: Fraction
    management_fee_years: int = Field(gt=0)
    recallable_share_range: tuple[Fraction, Fraction]

    @model_validator(mode="after")
    def _check(self) -> CashFlowConfig:
        if self.distribution_start_year > self.distribution_end_year:
            raise ValueError("distribution_start_year must not exceed distribution_end_year")
        for name, rng in (
            ("calls_per_commitment_range", self.calls_per_commitment_range),
            ("distributions_per_commitment_range", self.distributions_per_commitment_range),
        ):
            if not 1 <= rng[0] <= rng[1]:
                raise ValueError(f"{name} must satisfy 1 <= lo <= hi, got {rng}")
        lo, hi = self.terminal_paid_in_fraction_range
        if lo > hi:
            raise ValueError("terminal_paid_in_fraction_range must be ordered")
        if hi > 1.0:
            # Paid-in above commitment is only legitimate once recallable distributions have
            # actually been received, and the generator cannot know that when it sizes the call
            # schedule. Capping at 1.0 keeps the invariant true by construction as well as by
            # the runtime clip in flows.py.
            raise ValueError("terminal_paid_in_fraction_range must not exceed 1.0")
        if self.recallable_share_range[0] > self.recallable_share_range[1]:
            raise ValueError("recallable_share_range must be ordered")
        return self


class NavConfig(Base):
    """The J-curve. A piecewise-linear multiple on paid-in capital, in fund-life progress terms.

    The curve runs (0, initial_multiple) -> (trough_progress, trough_multiple) -> (1, terminal
    TVPI). Starting below 1.0 and dipping further is what produces the early paid-in-exceeds-value
    phase; the recovery to TVPI is the strategy-specific outcome drawn in StrategyParams.
    """

    initial_multiple: Positive
    trough_multiple: Positive
    trough_progress: Fraction
    quarterly_noise_sd: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _check(self) -> NavConfig:
        if self.trough_progress in (0.0, 1.0):
            raise ValueError("trough_progress must lie strictly between 0 and 1")
        return self


class FxConfig(Base):
    """EUR->USD as a mean-reverting log process.

    A pure random walk over fourteen years drifts to implausible levels. Ornstein-Uhlenbeck in log
    space keeps the series inside a believable band without the distribution-distorting clip that
    hard bounds would impose.
    """

    base_rate: Positive
    annual_vol: Positive
    mean_reversion: Fraction


class IndexConfig(Base):
    name: str = Field(min_length=1)
    start_level: Positive
    annual_drift: float
    annual_vol: Positive


class MarketConfig(Base):
    fx: FxConfig
    index: IndexConfig


class GeneratorConfig(Base):
    """Root config. One seed, one as-of date, and the entity blocks."""

    seed: int
    as_of_date: dt.date
    managers: ManagerConfig
    funds: FundConfig
    investors: InvestorConfig
    commitments: CommitmentConfig
    cash_flows: CashFlowConfig
    nav: NavConfig
    market: MarketConfig

    @model_validator(mode="after")
    def _check(self) -> GeneratorConfig:
        if self.commitments.funds_per_investor_range[1] > self.funds.count:
            raise ValueError(
                f"funds_per_investor_range upper bound {self.commitments.funds_per_investor_range[1]} "
                f"exceeds the {self.funds.count} funds available to commit to"
            )
        if self.as_of_date.year < self.funds.vintage_year_range[0]:
            raise ValueError("as_of_date precedes the earliest vintage year, so nothing could be generated")
        return self

    @property
    def history_start(self) -> dt.date:
        """First date any series needs to cover: 1 January of the earliest vintage year."""
        return dt.date(self.funds.vintage_year_range[0], 1, 1)


def load_config(path: str | Path) -> GeneratorConfig:
    """Load and validate a generator config from YAML."""
    text = Path(path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return GeneratorConfig.model_validate(raw)
