{% if profile_details.latest_updates %}
## Latest updates:
{% for update in profile_details.latest_updates %}
- {{ update }}
{% endfor %}
{% endif %}

{% if profile_details.next_milestones %}
## Next milestones:
{% for milestone in profile_details.next_milestones %}
- {{ milestone }}
{% endfor %}
{% endif %}

{% if profile_details.prograstination %}
## Currently prograstinating the following tasks:
{% for task in profile_details.prograstination %}
- {{ task }}
{% endfor %}
{% endif %}