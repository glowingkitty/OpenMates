{ start_for_all.md }
{ profile_details_for_all.md }
{ products_and_services_detailed.md }
{ updates_milestones_prograstination.md }



{% if profile_details.tools and profile_details.tools.project_management %}
# Tools we use, for:

## Project management
{% for tool in profile_details.tools.project_management %}
- {{ tool }}
{% endfor %}

{% endif %}



{% if profile_details.relevant_topics and profile_details.relevant_topics.business_development %}
# Topics that are relevant for us:

## Business development
{% for topic in profile_details.relevant_topics.business_development %}
- {{ topic }}
{% endfor %}

{% endif %}



{% if profile_details.partners %}
# Our partners:

{% for partner in profile_details.partners %}
- {{ partner }}
{% endfor %}

{% endif %}



{% if profile_details.additional_details and profile_details.additional_details.business %}
# Additional details:

{% if profile_details.additional_details.finance %}
## Finance:
{% for detail in profile_details.additional_details.finance %}
- {{ detail }}
{% endfor %}

{% endif %}

## Business:
{% for detail in profile_details.additional_details.business %}
- {{ detail }}
{% endfor %}

{% endif %}



{% if profile_details.planned_investments %}
# Our planned investments:

{% for investment in profile_details.planned_investments %}
- {{ investment }}
{% endfor %}

{% endif %}