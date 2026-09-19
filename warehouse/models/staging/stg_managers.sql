-- Renaming and casting only. `name` is qualified to manager_name here because three dimensions
-- carry a `name` column and an unqualified one is ambiguous the moment two are joined.
select
    cast(manager_id as varchar) as manager_id,
    cast(name as varchar) as manager_name,
    cast(hq_region as varchar) as hq_region,
    cast(founded_year as integer) as founded_year
from {{ source('raw', 'managers') }}
