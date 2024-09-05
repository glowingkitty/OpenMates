{ start_for_all.md }
{ profile_details_for_all.md }
{ products_and_services_detailed.md }
{ updates_milestones_prograstination.md }



{% if profile_details.tools and profile_details.tools.software_development %}
# Tools we use, for:

## Software development
{% for tool in profile_details.tools.software_development %}
- {{ tool }}
{% endfor %}

{% if profile_details.tools.web_development %}
## Web development
{% for tool in profile_details.tools.web_development %}
- {{ tool }}
{% endfor %}
{% endif %}

{% if profile_details.tools.project_management %}
## Project management
{% for tool in profile_details.tools.project_management %}
- {{ tool }}
{% endfor %}
{% endif %}

{% endif %}



{% if profile_details.relevant_topics and profile_details.relevant_topics.software_development %}
# Topics that are relevant for us:

## Software development
{% for topic in profile_details.relevant_topics.software_development %}
- {{ topic }}
{% endfor %}

{% endif %}


{ guidelines/guidelines_software_development.md }