{#
  Net asset value cannot be negative.

  An LP's exposure in a closed-end fund is bounded below by zero: the position can become
  worthless but it cannot owe more than the unfunded commitment, which is tracked separately. A
  negative NAV here would mean either a sign error in the currency conversion or distributions
  being netted off a value that had already been reduced by them.

  Zero is allowed and expected -- a fully liquidated fund reports exactly zero, which is a real
  value and distinct from the NULL that means "not reported for this quarter".
#}
{% test nav_non_negative(model, column_name) %}

select
    {{ column_name }} as nav
from {{ model }}
where {{ column_name }} is not null
  and {{ column_name }} < 0

{% endtest %}
