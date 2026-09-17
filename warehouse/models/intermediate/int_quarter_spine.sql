-- One row per fund x investor x quarter end, from the position's first capital call to the last
-- quarter it reports.
--
-- Built independently of the NAV table rather than derived from it. The two should agree row for
-- row, and building the grid from the flows means a NAV row missing from the middle of a
-- position's life shows up as a NULL in fct_nav_quarterly for the test to catch, instead of
-- silently shortening the series.
--
-- The reporting end is the position's last NAV quarter, falling back to the as-of quarter for a
-- position that has no NAV at all. A fund whose last NAV quarter precedes the as-of quarter has
-- liquidated -- that is how the raw layer signals liquidation, since fund life is not published.
--
-- The as-of date is read from the FX series rather than hard-coded or passed as a var. The
-- generator produces FX for every date from the earliest vintage through the as-of date and no
-- further, so max(rate_date) *is* the as-of date. Deriving it removes a constant that would
-- otherwise have to be kept in step with configs/generator.yaml by hand.

with bounds as (
    select
        min(flow_date) as lo,
        (select max(fx.rate_date) from {{ ref('stg_fx_rates') }} as fx) as hi
    from {{ ref('stg_cash_flows') }}
),

all_days as (
    {{ day_spine('bounds', 'lo', 'hi') }}
),

all_quarters as (
    select date as quarter_end
    from all_days
    where date = {{ quarter_end_date('date') }}
),

as_of as (
    select {{ quarter_end_date('max(rate_date)') }} as as_of_quarter
    from {{ ref('stg_fx_rates') }}
),

first_call as (
    select
        fund_id,
        investor_id,
        {{ quarter_end_date('min(flow_date)') }} as first_call_quarter
    from {{ ref('stg_cash_flows') }}
    where flow_type = 'capital_call'
    group by fund_id, investor_id
),

last_reported as (
    select
        fund_id,
        investor_id,
        max(quarter_end) as last_nav_quarter
    from {{ ref('stg_nav') }}
    group by fund_id, investor_id
),

pair_range as (
    select
        first_call.fund_id,
        first_call.investor_id,
        first_call.first_call_quarter,
        coalesce(
            last_reported.last_nav_quarter,
            (select a.as_of_quarter from as_of as a)
        ) as end_quarter
    from first_call
    left join last_reported
        on first_call.fund_id = last_reported.fund_id
        and first_call.investor_id = last_reported.investor_id
)

select
    pair_range.fund_id,
    pair_range.investor_id,
    all_quarters.quarter_end
from pair_range
inner join all_quarters
    on pair_range.first_call_quarter <= all_quarters.quarter_end
    and pair_range.end_quarter >= all_quarters.quarter_end
