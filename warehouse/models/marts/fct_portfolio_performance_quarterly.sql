-- Grain: investor_id x as_of_quarter.
--
-- Aggregated from the cash flows and NAV directly, **not** from fct_fund_performance_quarterly.
-- That distinction is load-bearing. A fund that liquidated in 2020 has no row in the fund-level
-- fact at 2024, so summing that fact would drop its historical paid-in and distributions out of
-- the investor's inception-to-date totals and overstate every ratio. Aggregating the flows with
-- flow_date <= quarter keeps a wound-up fund's history in the denominator, which is where it
-- belongs.
--
-- Ratios are ratios of sums, never averages of fund ratios. An average of DPIs weights a
-- USD 2m position the same as a USD 200m one and answers a question nobody asked.
--
-- net_irr is solved over every flow of every position pooled into one vector, in
-- int_portfolio_returns_by_quarter. IRR is not additive: no average of fund IRRs, weighted or
-- otherwise, equals the rate the pooled stream actually produced.
--
-- NAV is coalesced to zero here, unlike in the fund-level fact. At portfolio level a fund with no
-- NAV row at this quarter has liquidated and genuinely contributes zero residual value; the
-- not_null test on the fund-level grain is what guards against a real gap in the source.

with investor_quarters as (
    select distinct
        investor_id,
        quarter_end
    from {{ ref('int_quarter_spine') }}
),

flows as (
    select * from {{ ref('int_cash_flows_usd') }}
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
        stg_commitments.investor_id,
        stg_commitments.fund_id,
        stg_commitments.commitment_date,
        case
            when dim_fund.fund_currency = 'EUR' then stg_commitments.commitment_amount * eur_usd.fx_rate
            else stg_commitments.commitment_amount
        end as commitment_usd
    from {{ ref('stg_commitments') }} as stg_commitments
    inner join {{ ref('dim_fund') }} as dim_fund
        on stg_commitments.fund_id = dim_fund.fund_id
    left join eur_usd
        on stg_commitments.commitment_date = eur_usd.rate_date
        and dim_fund.fund_currency = 'EUR'
),

cumulative as (
    select
        investor_quarters.investor_id,
        investor_quarters.quarter_end,
        coalesce(sum(case when flows.flow_type = 'capital_call' then flows.amount_usd end), 0)
            as capital_calls_usd,
        coalesce(sum(case when flows.flow_type = 'management_fee' then flows.amount_usd end), 0)
            as management_fees_usd,
        coalesce(
            sum(case when flows.flow_type in ('capital_call', 'management_fee') then flows.amount_usd end),
            0
        ) as paid_in_usd,
        coalesce(
            sum(case when flows.flow_type in ('distribution', 'recallable_distribution') then flows.amount_usd end),
            0
        ) as distributions_usd,
        coalesce(
            sum(case when flows.flow_type = 'recallable_distribution' then flows.amount_usd end),
            0
        ) as recallable_distributions_usd
    from investor_quarters
    left join flows
        on investor_quarters.investor_id = flows.investor_id
        and investor_quarters.quarter_end >= flows.flow_date
    group by investor_quarters.investor_id, investor_quarters.quarter_end
),

committed as (
    select
        investor_quarters.investor_id,
        investor_quarters.quarter_end,
        coalesce(sum(commitments.commitment_usd), 0) as commitment_usd,
        count(commitments.fund_id) as fund_count
    from investor_quarters
    left join commitments
        on investor_quarters.investor_id = commitments.investor_id
        and investor_quarters.quarter_end >= commitments.commitment_date
    group by investor_quarters.investor_id, investor_quarters.quarter_end
),

nav as (
    select
        investor_id,
        quarter_end,
        sum(nav_usd) as nav_usd
    from {{ ref('int_nav_usd') }}
    group by investor_id, quarter_end
),

portfolio_returns as (
    select * from {{ ref('int_portfolio_returns_by_quarter') }}
)

select
    cumulative.investor_id,
    cumulative.quarter_end as as_of_quarter,
    committed.commitment_usd,
    committed.fund_count,
    cumulative.paid_in_usd,
    cumulative.capital_calls_usd,
    cumulative.management_fees_usd,
    cumulative.distributions_usd,
    cumulative.recallable_distributions_usd,
    committed.commitment_usd + cumulative.recallable_distributions_usd - cumulative.paid_in_usd
        as unfunded_usd,
    coalesce(nav.nav_usd, 0) as nav_usd,
    case when cumulative.paid_in_usd > 0 then cumulative.distributions_usd / cumulative.paid_in_usd end as dpi,
    case when cumulative.paid_in_usd > 0 then coalesce(nav.nav_usd, 0) / cumulative.paid_in_usd end as rvpi,
    case
        when cumulative.paid_in_usd > 0
            then (cumulative.distributions_usd + coalesce(nav.nav_usd, 0)) / cumulative.paid_in_usd
    end as tvpi,
    portfolio_returns.net_irr,
    portfolio_returns.ks_pme,
    cumulative.quarter_end = max(cumulative.quarter_end) over (
        partition by cumulative.investor_id
    ) as is_latest_quarter
from cumulative
inner join committed
    on cumulative.investor_id = committed.investor_id
    and cumulative.quarter_end = committed.quarter_end
left join nav
    on cumulative.investor_id = nav.investor_id
    and cumulative.quarter_end = nav.quarter_end
left join portfolio_returns
    on cumulative.investor_id = portfolio_returns.investor_id
    and cumulative.quarter_end = portfolio_returns.as_of_quarter
