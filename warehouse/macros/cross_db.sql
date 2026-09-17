{#
  SQL constructs that DuckDB and Snowflake spell differently, resolved per adapter
  via adapter.dispatch. default__ is the DuckDB form (used by the local target);
  snowflake__ is the Snowflake form.

  Adapted from C0k11/quantai warehouse/macros/cross_db.sql (MIT). Comments
  translated from Chinese; the dispatch namespace follows this project's
  dbt_project.yml name. The upstream file carried five macros; iso_day_of_week,
  year_month and local_date_from_utc were dropped because private markets data has
  no trading calendar and no intraday UTC timestamps to convert.
#}

{# Calendar-day series: one row per day from lo to hi inclusive, taken from bounds_cte, column named date. #}
{% macro day_spine(bounds_cte, lo, hi) -%}
    {{ return(adapter.dispatch('day_spine', 'pm_bi_warehouse')(bounds_cte, lo, hi)) }}
{%- endmacro %}

{% macro default__day_spine(bounds_cte, lo, hi) -%}
    select cast(unnest(generate_series({{ lo }}, {{ hi }}, interval '1 day')) as date) as date
    from {{ bounds_cte }}
{%- endmacro %}

{% macro snowflake__day_spine(bounds_cte, lo, hi) -%}
    select dateadd(day, g.value::int, b.{{ lo }})::date as date
    from {{ bounds_cte }} b,
        lateral flatten(input => array_generate_range(0, datediff(day, b.{{ lo }}, b.{{ hi }}) + 1)) g
{%- endmacro %}

{#
  ASOF left join: for each left row take the nearest right row where right_time <= left_time,
  NULL when there is no match.

  Needed here because cash flows land on irregular dates but FX rates and NAV marks land on their
  own schedule, so converting a flow means reaching for the most recent rate on or before it.

  The two dialects put the time comparison in different places: DuckDB takes it in ON alongside the
  equality, Snowflake requires it in MATCH_CONDITION and allows only equality conditions in ON.
  Snowflake's ASOF JOIN already yields NULL on no match, so it needs no LEFT keyword.
#}
{% macro asof_left_join(relation, alias, equal_on, left_time, right_time) -%}
    {{ return(adapter.dispatch('asof_left_join', 'pm_bi_warehouse')(relation, alias, equal_on, left_time, right_time)) }}
{%- endmacro %}

{% macro default__asof_left_join(relation, alias, equal_on, left_time, right_time) -%}
    asof left join {{ relation }} {{ alias }}
        on {{ equal_on }} and {{ right_time }} <= {{ left_time }}
{%- endmacro %}

{% macro snowflake__asof_left_join(relation, alias, equal_on, left_time, right_time) -%}
    asof join {{ relation }} {{ alias }}
        match_condition ({{ left_time }} >= {{ right_time }})
        on {{ equal_on }}
{%- endmacro %}
