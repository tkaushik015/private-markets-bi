{#
  TVPI must equal DPI + RVPI exactly, to floating-point tolerance.

  This is an identity, not an approximation: all three share the same paid-in denominator, so
  (distributions + NAV) / paid_in is (distributions / paid_in) + (NAV / paid_in) by construction.
  Testing it catches the mistake that breaks it -- computing one of the three over a different
  denominator, a different as-of date or a different set of flow types. That error is invisible in
  any single column and obvious in the identity.

  Rows where paid-in is zero are excluded: all three ratios are NULL there, and NULL = NULL + NULL
  is not a meaningful comparison. The not_null tests on the ratio columns cover whether those
  NULLs are legitimate.
#}
{% test tvpi_equals_dpi_plus_rvpi(model, column_name, dpi_column, rvpi_column, tolerance=1e-9) %}

select
    {{ column_name }} as tvpi,
    {{ dpi_column }} as dpi,
    {{ rvpi_column }} as rvpi,
    abs({{ column_name }} - ({{ dpi_column }} + {{ rvpi_column }})) as identity_gap
from {{ model }}
where {{ column_name }} is not null
  and {{ dpi_column }} is not null
  and {{ rvpi_column }} is not null
  and abs({{ column_name }} - ({{ dpi_column }} + {{ rvpi_column }})) > {{ tolerance }}

{% endtest %}
