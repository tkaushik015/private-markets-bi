{#
  Uniqueness across a set of columns, which is what a compound grain needs.

  Hand-written rather than taken from dbt_utils. The project has no package dependencies, and this
  one test is the only reason it would have needed them; carrying a package to get it would mean a
  `dbt deps` network call in CI for twelve lines of SQL.

  Every fact in this project declares its grain and is tested with this, so a duplicate row cannot
  reach a mart and quietly double a sum.
#}
{% test unique_combination_of_columns(model, combination_of_columns) %}

{%- set column_list = combination_of_columns | join(', ') -%}

select
    {{ column_list }},
    count(*) as duplicate_rows
from {{ model }}
group by {{ column_list }}
having count(*) > 1

{% endtest %}
