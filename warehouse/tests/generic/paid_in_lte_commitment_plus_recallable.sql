{#
  Cumulative paid-in must never exceed commitment plus recallable distributions received to date.

  An LP cannot be drawn more than it committed. The one legitimate exception is capital returned
  as a recallable distribution, which restores callable headroom -- so the ceiling is
  commitment + recallable-to-date, not commitment alone.

  The generator enforces this at source and asserts it in pytest. Testing it again here is not
  redundant: this version checks it survived the warehouse. A currency conversion applied to
  paid-in but not to commitment, or a cumulative window that reaches past the as-of quarter, would
  both break it, and both are mistakes this layer can make and the generator cannot.

  The tolerance is a currency tolerance, not a relative one: paid-in and commitment are both
  rounded to cents on the way in, so a legitimate row can sit a fraction of a cent over.
#}
{% test paid_in_lte_commitment_plus_recallable(
    model,
    column_name,
    commitment_column,
    recallable_column,
    tolerance=0.01
) %}

select
    {{ column_name }} as paid_in,
    {{ commitment_column }} as commitment,
    {{ recallable_column }} as recallable_to_date,
    {{ column_name }} - ({{ commitment_column }} + {{ recallable_column }}) as overdrawn_by
from {{ model }}
where {{ column_name }} is not null
  and {{ commitment_column }} is not null
  and {{ column_name }} > {{ commitment_column }} + coalesce({{ recallable_column }}, 0) + {{ tolerance }}

{% endtest %}
