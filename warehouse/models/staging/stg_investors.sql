-- Renaming and casting only.
select
    cast(investor_id as varchar) as investor_id,
    cast(name as varchar) as investor_name,
    cast(investor_type as varchar) as investor_type
from {{ source('raw', 'investors') }}
