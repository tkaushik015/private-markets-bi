-- Cumulative cash flow position per fund x investor as at each quarter end.
--
-- Every figure is inception-to-date as at `quarter_end`, not a per-quarter movement. That is the
-- as-of convention the whole metrics layer uses: DPI, RVPI and TVPI at a quarter are ratios of
-- inception-to-date totals, never of one quarter's activity.
--
-- The join is on flow_date <= quarter_end, so the same flow contributes to every later quarter.
-- Amounts are unsigned here: paid_in and distributions are both positive magnitudes, because a
-- ratio of two positive numbers is easier to reason about than one built from signed sums. The
-- signed vector is what IRR needs, and that lives in int_cash_flows_usd.

with spine as (
    select * from {{ ref('int_quarter_spine') }}
),

flows as (
    select * from {{ ref('int_cash_flows_usd') }}
)

select
    spine.fund_id,
    spine.investor_id,
    spine.quarter_end,
    coalesce(sum(case when flows.flow_type = 'capital_call' then flows.amount_usd end), 0) as capital_calls_usd,
    coalesce(sum(case when flows.flow_type = 'management_fee' then flows.amount_usd end), 0) as management_fees_usd,
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
    ) as recallable_distributions_usd,
    -- Fund-currency totals alongside the USD ones. The contractual cap on how much an LP can be
    -- drawn is denominated in the fund's currency, so that is the only currency the invariant
    -- holds in: converting each call at its own date's rate lets the USD total legitimately
    -- exceed the USD value of the commitment at signing, purely from FX drift. Keeping the local
    -- figures means the constraint can be tested where it is actually true.
    coalesce(
        sum(case when flows.flow_type in ('capital_call', 'management_fee') then flows.amount end),
        0
    ) as paid_in_local,
    coalesce(
        sum(case when flows.flow_type = 'recallable_distribution' then flows.amount end),
        0
    ) as recallable_distributions_local,
    count(flows.cash_flow_id) as flow_count
from spine
left join flows
    on spine.fund_id = flows.fund_id
    and spine.investor_id = flows.investor_id
    and spine.quarter_end >= flows.flow_date
group by spine.fund_id, spine.investor_id, spine.quarter_end
