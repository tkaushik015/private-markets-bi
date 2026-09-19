{#
  Make +schema: staging / intermediate / marts land in a schema of exactly that name.
  dbt's default behaviour concatenates the target schema onto the custom one,
  producing main_staging.

  Adapted from C0k11/quantai warehouse/macros/generate_schema_name.sql (MIT).
  Comment translated from Chinese. Phase 3 adds the snowflake_ci prefix so a PR
  build writes CI_<id>_staging rather than overwriting the shared staging schema.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif target.name == 'snowflake_ci' -%}
        {# CI builds write CI_<id>_STAGING / CI_<id>_MARTS so they cannot overwrite shared MARTS. #}
        {{ target.schema }}_{{ custom_schema_name | trim }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
