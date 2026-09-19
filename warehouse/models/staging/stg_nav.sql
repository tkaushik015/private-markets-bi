-- Renaming and casting only.
select
    cast(fund_id as varchar) as fund_id,
    cast(investor_id as varchar) as investor_id,
    cast(quarter_end as date) as quarter_end,
    cast(nav as double) as nav,
    cast(currency as varchar) as nav_currency
from {{ source('raw', 'nav') }}
