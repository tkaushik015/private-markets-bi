-- One row per fund.
--
-- vintage_start_date is derived here rather than in staging, which is kept to renaming and
-- casting. It is 1 January of the vintage year: the reference point fund age is measured from,
-- and the point the lifecycle model treats as the start of the fund's life.
select
    fund_id,
    manager_id,
    fund_name,
    strategy,
    vintage_year,
    cast(cast(vintage_year as varchar) || '-01-01' as date) as vintage_start_date,
    fund_currency,
    fund_size,
    geography_focus
from {{ ref('stg_funds') }}
