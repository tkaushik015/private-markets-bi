-- Daily calendar spine with quarter-end flags, covering the full reporting range.
--
-- Daily rather than quarterly because cash flows land on irregular dates and need a date
-- dimension too, while NAV and every performance metric sit on quarter ends. One dimension with
-- an is_quarter_end flag serves both, and `quarter_end_date` lets a daily fact roll up to the
-- quarter it belongs to without any date arithmetic in the report layer.
--
-- The range runs from the earliest cash flow to the as-of date, which is read from the FX series
-- for the reason given in int_quarter_spine.
--
-- Replaces the equities dim_date this project inherited, which was a trading-day calendar with an
-- is_trading_day flag against the NYSE schedule. Private markets have no trading calendar:
-- capital is called when it is called, and valuations land on quarter ends whether or not those
-- are business days. 30 June 2024 is a Sunday and is still a valuation date.

with bounds as (
    select
        min(flow_date) as lo,
        (select max(fx.rate_date) from {{ ref('stg_fx_rates') }} as fx) as hi
    from {{ ref('stg_cash_flows') }}
),

all_days as (
    {{ day_spine('bounds', 'lo', 'hi') }}
)

select
    date as date_day,
    cast(extract(year from date) as integer) as calendar_year,
    cast(extract(quarter from date) as integer) as calendar_quarter,
    cast(extract(month from date) as integer) as calendar_month,
    cast(extract(day from date) as integer) as day_of_month,
    cast(cast(extract(year from date) as varchar) || '-Q' || cast(extract(quarter from date) as varchar) as varchar)
        as year_quarter_label,
    {{ quarter_end_date('date') }} as quarter_end_date,
    date = {{ quarter_end_date('date') }} as is_quarter_end,
    date = {{ month_end_date('date') }} as is_month_end,
    extract(month from date) = 12 and extract(day from date) = 31 as is_year_end
from all_days
