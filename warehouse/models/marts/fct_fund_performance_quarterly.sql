-- Grain: fund_id x investor_id x as_of_quarter.
--
-- One row per position per quarter end, carrying that position's inception-to-date performance as
-- at that quarter. It is a point-in-time series, not a single snapshot: `is_latest_quarter` picks
-- out the most recent row per position for reporting that wants only current figures.
--
-- Conventions, all of them inception-to-date as at as_of_quarter and all in USD:
--   paid_in        capital calls + management fees. Fees count because they are drawn from the
--                  commitment, which is what puts a young position below 1.0x before value accrues.
--   distributions  distributions + recallable distributions.
--   unfunded       commitment + recallable-to-date - paid_in. Recallable distributions restore
--                  callable headroom, so they raise the ceiling rather than reducing the draw.
--
-- The commitment envelope is also published in the fund's own currency (commitment_local,
-- paid_in_local, unfunded_local). That is not duplication for convenience: the contractual limit
-- on how much an LP can be drawn is denominated in the fund's currency, and it is the only
-- currency the limit holds in. Each call is converted at the rate on its own date while the
-- commitment is fixed at the rate on signing, so for a EUR fund whose currency strengthened the
-- USD total can legitimately exceed the USD commitment -- measured at a maximum of 2.47% on this
-- seed, with the fund-currency paid-in/commitment ratio never above 0.9784. The paid-in cap test
-- therefore runs on the local columns.
--   dpi            distributions / paid_in
--   rvpi           nav / paid_in
--   tvpi           (distributions + nav) / paid_in, which is dpi + rvpi by construction
--   net_irr        solved in Python over the signed flows plus terminal NAV; see
--                  int_returns_by_quarter. NULL, never 0, where no rate exists.
--   ks_pme         Kaplan-Schoar against the synthetic public index.
--
-- Ratios are NULL rather than 0 where paid_in is 0, because a position that has been drawn nothing
-- has no multiple -- it is not a position that has broken even.
--
-- nav_usd is taken from fct_nav_quarterly without a coalesce on purpose. A liquidated fund reports
-- a real 0; a quarter with no NAV row at all would be a gap in the source, and that must surface
-- as NULL for the test to catch rather than be silently read as worthless.

with cumulative as (
    select * from {{ ref('int_cumulative_flows_by_quarter') }}
),

nav as (
    select * from {{ ref('fct_nav_quarterly') }}
),

position_returns as (
    select * from {{ ref('int_returns_by_quarter') }}
),

eur_usd as (
    select
        rate_date,
        fx_rate
    from {{ ref('stg_fx_rates') }}
    where from_currency = 'EUR' and to_currency = 'USD'
),

commitments as (
    select
        stg_commitments.fund_id,
        stg_commitments.investor_id,
        stg_commitments.commitment_date,
        case
            when dim_fund.fund_currency = 'EUR' then stg_commitments.commitment_amount * eur_usd.fx_rate
            else stg_commitments.commitment_amount
        end as commitment_usd,
        stg_commitments.commitment_amount as commitment_local,
        dim_fund.fund_currency,
        dim_fund.vintage_start_date
    from {{ ref('stg_commitments') }} as stg_commitments
    inner join {{ ref('dim_fund') }} as dim_fund
        on stg_commitments.fund_id = dim_fund.fund_id
    left join eur_usd
    -- The commitment is converted at the rate on the date it was signed, which is the date the
    -- obligation was struck. Converting it at each reporting quarter's rate instead would make
        -- unfunded commitment move with FX even in a quarter with no capital activity at all.
        on stg_commitments.commitment_date = eur_usd.rate_date
        and dim_fund.fund_currency = 'EUR'
)

select
    cumulative.fund_id,
    cumulative.investor_id,
    cumulative.quarter_end as as_of_quarter,
    commitments.commitment_usd,
    cumulative.paid_in_usd,
    cumulative.capital_calls_usd,
    cumulative.management_fees_usd,
    cumulative.distributions_usd,
    cumulative.recallable_distributions_usd,
    commitments.commitment_usd + cumulative.recallable_distributions_usd - cumulative.paid_in_usd
        as unfunded_usd,
    commitments.fund_currency,
    commitments.commitment_local,
    cumulative.paid_in_local,
    cumulative.recallable_distributions_local,
    commitments.commitment_local + cumulative.recallable_distributions_local - cumulative.paid_in_local
        as unfunded_local,
    nav.nav_usd,
    case when cumulative.paid_in_usd > 0 then cumulative.distributions_usd / cumulative.paid_in_usd end as dpi,
    case when cumulative.paid_in_usd > 0 then nav.nav_usd / cumulative.paid_in_usd end as rvpi,
    case
        when cumulative.paid_in_usd > 0
            then (cumulative.distributions_usd + nav.nav_usd) / cumulative.paid_in_usd
    end as tvpi,
    position_returns.net_irr,
    position_returns.ks_pme,
    {{ days_between('commitments.vintage_start_date', 'cumulative.quarter_end') }} / 365.25 as fund_age_years,
    cumulative.quarter_end = max(cumulative.quarter_end) over (
        partition by cumulative.fund_id, cumulative.investor_id
    ) as is_latest_quarter
from cumulative
inner join commitments
    on cumulative.fund_id = commitments.fund_id
    and cumulative.investor_id = commitments.investor_id
left join nav
    on cumulative.fund_id = nav.fund_id
    and cumulative.investor_id = nav.investor_id
    and cumulative.quarter_end = nav.quarter_end
left join position_returns
    on cumulative.fund_id = position_returns.fund_id
    and cumulative.investor_id = position_returns.investor_id
    and cumulative.quarter_end = position_returns.as_of_quarter
