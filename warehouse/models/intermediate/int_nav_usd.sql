-- Quarter-end NAV converted to USD at the rate on the quarter-end date itself.
--
-- The quarter end is the valuation date, so it is also the conversion date; using any other date
-- would mix a value measured at one moment with a rate from another. This is the reason the FX
-- series is calendar-daily: 30 June 2024 is a Sunday, and a business-day rate table would leave
-- that quarter's EUR NAV unconvertible.

with nav as (
    select * from {{ ref('stg_nav') }}
),

eur_usd as (
    select
        rate_date,
        fx_rate
    from {{ ref('stg_fx_rates') }}
    where from_currency = 'EUR' and to_currency = 'USD'
)

select
    nav.fund_id,
    nav.investor_id,
    nav.quarter_end,
    nav.nav,
    nav.nav_currency,
    case
        when nav.nav_currency = 'EUR' then nav.nav * eur_usd.fx_rate
        else nav.nav
    end as nav_usd
from nav
left join eur_usd
    on nav.quarter_end = eur_usd.rate_date
    and nav.nav_currency = 'EUR'
