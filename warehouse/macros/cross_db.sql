{#
  SQL constructs that DuckDB and Snowflake spell differently, resolved per adapter
  via adapter.dispatch. default__ is the DuckDB form (used by the local target);
  snowflake__ is the Snowflake form.

  Adapted from C0k11/quantai warehouse/macros/cross_db.sql (MIT). Comments
  translated from Chinese; the dispatch namespace is lp_lens_warehouse, which must
  stay equal to the dbt project name Phase 2 declares in dbt_project.yml. The
  upstream file carried five macros; iso_day_of_week, year_month and
  local_date_from_utc were dropped because private markets data has no trading
  calendar and no intraday UTC timestamps to convert.
#}

{# Calendar-day series: one row per day from lo to hi inclusive, taken from bounds_cte, column named date. #}
{% macro day_spine(bounds_cte, lo, hi) -%}
    {{ return(adapter.dispatch('day_spine', 'lp_lens_warehouse')(bounds_cte, lo, hi)) }}
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
    {{ return(adapter.dispatch('asof_left_join', 'lp_lens_warehouse')(relation, alias, equal_on, left_time, right_time)) }}
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

{#
  Quarter end containing a date: 31 March, 30 June, 30 September or 31 December.

  Added in Phase 2. Snowflake's last_day takes a date part, so a quarter end is one call; DuckDB's
  last_day is month-only, so the quarter has to be truncated and walked forward. DuckDB also
  promotes DATE + INTERVAL to TIMESTAMP, hence the cast back to DATE -- without it the quarter end
  would not compare equal to a date column.
#}
{% macro quarter_end_date(date_expr) -%}
    {{ return(adapter.dispatch('quarter_end_date', 'lp_lens_warehouse')(date_expr)) }}
{%- endmacro %}

{% macro default__quarter_end_date(date_expr) -%}
    cast(date_trunc('quarter', {{ date_expr }}) + interval '3 months' - interval '1 day' as date)
{%- endmacro %}

{% macro snowflake__quarter_end_date(date_expr) -%}
    last_day({{ date_expr }}, 'quarter')
{%- endmacro %}

{#
  Month end containing a date. Snowflake's last_day defaults to the month, DuckDB needs the
  truncate-and-step form and the cast back from TIMESTAMP.
#}
{% macro month_end_date(date_expr) -%}
    {{ return(adapter.dispatch('month_end_date', 'lp_lens_warehouse')(date_expr)) }}
{%- endmacro %}

{% macro default__month_end_date(date_expr) -%}
    cast(date_trunc('month', {{ date_expr }}) + interval '1 month' - interval '1 day' as date)
{%- endmacro %}

{% macro snowflake__month_end_date(date_expr) -%}
    last_day({{ date_expr }})
{%- endmacro %}

{#
  Whole days from start to end. Used for fund age, which is then divided by 365.25 rather than
  being taken as a difference of calendar years -- a fund with a January vintage and a fund with a
  December vintage are not the same age at the same quarter end.

  DuckDB wants the date part as a string literal; Snowflake takes it as an identifier.
#}
{% macro days_between(start_expr, end_expr) -%}
    {{ return(adapter.dispatch('days_between', 'lp_lens_warehouse')(start_expr, end_expr)) }}
{%- endmacro %}

{% macro default__days_between(start_expr, end_expr) -%}
    date_diff('day', {{ start_expr }}, {{ end_expr }})
{%- endmacro %}

{% macro snowflake__days_between(start_expr, end_expr) -%}
    datediff(day, {{ start_expr }}, {{ end_expr }})
{%- endmacro %}
