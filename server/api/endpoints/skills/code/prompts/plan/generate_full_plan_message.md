Basic Requirements:
{{ q_and_a_basics | tojson }}

{%- if q_and_a_followup %}
Follow-up Questions:
{{ q_and_a_followup | tojson }}
{%- endif %}

{%- if folder_tree %}
Folder Structure:
{{ folder_tree | tojson }}
{%- endif %}

{%- if other_context %}
Additional Context:
{{ other_context | tojson }}
{%- endif %}