-- Grain: fund_id x investor_id x quarter_end.
--
-- Driven off int_quarter_spine rather than off the NAV table, so a quarter missing from the middle
-- of a position's reporting history appears as a NULL nav_usd for the not_null test to fail on,
-- instead of vanishing from the series without trace.
--
-- The spine ends at the position's last reported quarter, so a liquidated fund has no rows after
-- liquidation. Its final row carries nav = 0, which is a real reported value -- the fund holds
-- nothing -- and is deliberately distinct from a NULL, which would mean not reported.

with spine as (
    select * from {{ ref('int_quarter_spine') }}
),

nav as (
    select * from {{ ref('int_nav_usd') }}
)

select
    spine.fund_id,
    spine.investor_id,
    spine.quarter_end,
    nav.nav,
    nav.nav_currency,
    nav.nav_usd
from spine
left join nav
    on spine.fund_id = nav.fund_id
    and spine.investor_id = nav.investor_id
    and spine.quarter_end = nav.quarter_end
