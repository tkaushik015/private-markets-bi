-- One row per strategy actually present in the fund population.
--
-- strategy_group is an assigned rollup, not a property of the source data: the raw layer carries
-- only the seven strategy names. It exists so a report can aggregate to a coarser level without
-- each report inventing its own grouping. Being an assignment, it belongs in one documented
-- place rather than in a slicer definition.
--
-- Built from the funds that exist rather than from a fixed list, so a strategy with no funds does
-- not appear as an empty row in every breakdown.
with strategies as (
    select distinct strategy as strategy_name
    from {{ ref('stg_funds') }}
)

select
    strategy_name,
    case strategy_name
        when 'Buyout' then 'Private Equity'
        when 'Venture' then 'Private Equity'
        when 'Growth' then 'Private Equity'
        when 'Secondaries' then 'Private Equity'
        when 'Private Credit' then 'Private Credit'
        when 'Real Estate' then 'Real Assets'
        when 'Infrastructure' then 'Real Assets'
    end as strategy_group
from strategies
