-- Renaming and casting only. commitment_amount is in the fund's currency.
select
    cast(commitment_id as varchar) as commitment_id,
    cast(investor_id as varchar) as investor_id,
    cast(fund_id as varchar) as fund_id,
    cast(commitment_amount as double) as commitment_amount,
    cast(commitment_date as date) as commitment_date
from {{ source('raw', 'commitments') }}
