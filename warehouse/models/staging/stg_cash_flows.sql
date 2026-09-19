-- Renaming and casting only. `amount` stays an unsigned magnitude at this layer; the sign
-- convention is applied once, in int_cash_flows_usd.
select
    cast(cash_flow_id as varchar) as cash_flow_id,
    cast(fund_id as varchar) as fund_id,
    cast(investor_id as varchar) as investor_id,
    cast(flow_date as date) as flow_date,
    cast(flow_type as varchar) as flow_type,
    cast(amount as double) as amount,
    cast(currency as varchar) as flow_currency
from {{ source('raw', 'cash_flows') }}
