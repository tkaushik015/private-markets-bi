-- Renaming and casting only.
select
    cast(index_date as date) as index_date,
    cast(index_name as varchar) as index_name,
    cast(level as double) as index_level
from {{ source('raw', 'public_index') }}
