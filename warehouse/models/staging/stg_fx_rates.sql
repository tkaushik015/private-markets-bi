-- Renaming and casting only.
select
    cast(rate_date as date) as rate_date,
    cast(from_currency as varchar) as from_currency,
    cast(to_currency as varchar) as to_currency,
    cast(rate as double) as fx_rate
from {{ source('raw', 'fx_rates') }}
