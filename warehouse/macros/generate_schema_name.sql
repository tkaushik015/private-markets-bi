{#
  Make +schema: staging / intermediate / marts land in a schema of exactly that name.
  dbt's default behaviour concatenates the target schema onto the custom one,
  producing main_staging.

  Adapted from C0k11/quantai warehouse/macros/generate_schema_name.sql (MIT).
  Comment translated from Chinese; logic unchanged.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
