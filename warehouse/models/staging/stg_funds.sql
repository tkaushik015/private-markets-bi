-- Renaming and casting only.
select
    cast(fund_id as varchar) as fund_id,
    cast(manager_id as varchar) as manager_id,
    cast(fund_name as varchar) as fund_name,
    cast(strategy as varchar) as strategy,
    cast(vintage_year as integer) as vintage_year,
    cast(currency as varchar) as fund_currency,
    cast(fund_size as double) as fund_size,
    cast(geography_focus as varchar) as geography_focus
from {{ source('raw', 'funds') }}
