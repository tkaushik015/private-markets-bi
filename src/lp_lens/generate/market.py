"""FX rates and the public index: the two reference series the metrics layer needs.

Both are calendar-daily rather than business-daily, covering every date from the earliest vintage
to the as-of date. That is a deliberate choice, not laziness. Quarter ends are real quarter-end
dates, and 30 June 2024 is a Sunday; a business-day series would leave a EUR-denominated NAV on
that date with no rate to convert it at. Generating every calendar date makes "FX covers every
date that has a EUR flow or NAV" true by construction instead of by a lookup rule that has to be
reimplemented identically in dbt and in Python.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np

from .config import GeneratorConfig

DAYS_PER_YEAR = 365.0


def daily_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    """Every calendar date from start to end inclusive."""
    if end < start:
        raise ValueError(f"end {end} precedes start {start}")
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def build_fx_rates(config: GeneratorConfig, rng: np.random.Generator) -> list[dict]:
    """EUR->USD as a mean-reverting log process, one row per calendar day.

    Ornstein-Uhlenbeck in log space rather than a random walk: over fourteen years a driftless
    walk at 8% annual vol wanders far enough to quote implausible rates, and clipping it to a band
    would pile probability mass on the bounds. Mean reversion keeps the series inside a believable
    range while leaving the distribution smooth.
    """
    cfg = config.market.fx
    dates = daily_dates(config.history_start, config.as_of_date)
    daily_vol = cfg.annual_vol / math.sqrt(DAYS_PER_YEAR)
    log_base = math.log(cfg.base_rate)
    shocks = rng.normal(0.0, daily_vol, size=len(dates))

    rows: list[dict] = []
    log_rate = log_base
    for rate_date, shock in zip(dates, shocks, strict=True):
        rows.append(
            {
                "rate_date": rate_date,
                "from_currency": "EUR",
                "to_currency": "USD",
                "rate": round(math.exp(log_rate), 6),
            }
        )
        log_rate += cfg.mean_reversion * (log_base - log_rate) + float(shock)
    return rows


def build_public_index(config: GeneratorConfig, rng: np.random.Generator) -> list[dict]:
    """A synthetic total-return index for PME, one level per calendar day.

    Geometric Brownian motion with drift. Total return means the level already includes reinvested
    income, so a PME calculation indexes fund cash flows straight onto it with no dividend
    adjustment. The name is deliberately not that of any real index.
    """
    cfg = config.market.index
    dates = daily_dates(config.history_start, config.as_of_date)
    daily_vol = cfg.annual_vol / math.sqrt(DAYS_PER_YEAR)
    daily_drift = (cfg.annual_drift - 0.5 * cfg.annual_vol**2) / DAYS_PER_YEAR
    shocks = rng.normal(0.0, daily_vol, size=len(dates))

    # First row sits at start_level exactly, so the series has a stated base rather than one day
    # of unexplained drift before it begins.
    log_levels = math.log(cfg.start_level) + np.concatenate(([0.0], np.cumsum(daily_drift + shocks[1:])))

    return [
        {
            "index_date": index_date,
            "index_name": cfg.name,
            "level": round(float(math.exp(log_level)), 4),
        }
        for index_date, log_level in zip(dates, log_levels, strict=True)
    ]
