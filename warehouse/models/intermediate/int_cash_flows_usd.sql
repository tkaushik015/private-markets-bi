-- Cash flows converted to USD and signed once, here, for the whole project.
--
-- Currency: EUR flows use the rate on the flow date itself. The FX table is calendar-daily and
-- covers every date in range, so this is an equi-join rather than an as-of lookup. That is the
-- stronger choice: a missing rate becomes a NULL that the not_null test on amount_usd fails,
-- whereas an as-of join would silently carry a stale rate forward and report a converted figure
-- that looks fine. asof_left_join is kept in macros/cross_db.sql for Phase 3, where a
-- Snowflake-loaded rate table may be business-day only and a weekend quarter end will need it.
--
-- Sign: this CASE is the SQL half of the convention documented in lp_lens.generate.flows and
-- implemented in FLOW_DIRECTION. The two are separate expressions of one rule, so
-- tests/test_marts_reconcile.py asserts they agree rather than trusting that they do.

with flows as (
    select * from {{ ref('stg_cash_flows') }}
),

eur_usd as (
    select
        rate_date,
        fx_rate
    from {{ ref('stg_fx_rates') }}
    where from_currency = 'EUR' and to_currency = 'USD'
),

converted as (
    select
        flows.cash_flow_id,
        flows.fund_id,
        flows.investor_id,
        flows.flow_date,
        flows.flow_type,
        flows.amount,
        flows.flow_currency,
        case
            when flows.flow_currency = 'EUR' then flows.amount * eur_usd.fx_rate
            else flows.amount
        end as amount_usd,
        case
            when flows.flow_type in ('capital_call', 'management_fee') then -1
            else 1
        end as flow_direction
    from flows
    left join eur_usd
        on flows.flow_date = eur_usd.rate_date
        and flows.flow_currency = 'EUR'
)

select
    cash_flow_id,
    fund_id,
    investor_id,
    flow_date,
    flow_type,
    amount,
    flow_currency,
    amount_usd,
    flow_direction,
    flow_direction * amount_usd as signed_amount_usd
from converted
