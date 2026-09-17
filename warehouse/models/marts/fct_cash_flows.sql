-- Grain: one row per cash flow.
--
-- Both the source magnitude and the signed USD figure are published. `amount` is unsigned with the
-- direction in `flow_type`, which is how the source states it; `signed_amount_usd` is the LP-view
-- signed figure the IRR needs. Publishing both means a consumer never has to re-derive the sign
-- convention, and cannot get it wrong.

select
    cash_flow_id,
    fund_id,
    investor_id,
    flow_date,
    flow_type,
    amount,
    flow_currency,
    amount_usd,
    flow_direction,
    signed_amount_usd
from {{ ref('int_cash_flows_usd') }}
