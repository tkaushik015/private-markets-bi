-- One row per limited partner.
select
    investor_id,
    investor_name,
    investor_type
from {{ ref('stg_investors') }}
