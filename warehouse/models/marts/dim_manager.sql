-- One row per general partner.
select
    manager_id,
    manager_name,
    hq_region,
    founded_year
from {{ ref('stg_managers') }}
