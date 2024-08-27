Basic Requirements:
{{ q_and_a_basics | tojson }}

{%- if folder_tree %}
Folder Structure:
{{ folder_tree | tojson }}
{%- endif %}

{%- if other_context %}
Additional Context:
{{ other_context | tojson }}
{%- endif %}