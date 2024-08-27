Basic Requirements:
```json
{{ q_and_a_basics | tojson }}
```

{%- if folder_tree %}
Folder Structure:
```json
{{ folder_tree | tojson }}
```
{%- endif %}

{%- if other_context %}
Additional Context:
```json
{{ other_context | tojson }}
```
{%- endif %}