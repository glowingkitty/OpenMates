{ start_for_all.md }
{ profile_details_for_all.md }
{ products_and_services_detailed.md }
{ updates_milestones_prograstination.md }



{% if profile_details.tools and profile_details.tools.hackspace %}
# Tools we use, for:

## Tools at the hackspace
{% for tool in profile_details.tools.hackspace %}
- {{ tool }}
{% endfor %}

{% endif %}



{% if profile_details.relevant_topics and profile_details.relevant_topics.prototyping %}
# Topics that are relevant for us:

## Prototyping
{% for topic in profile_details.relevant_topics.prototyping %}
- {{ topic }}
{% endfor %}

{% endif %}



{% if profile_details.partners %}
# Our partners:

{% for partner in profile_details.partners %}
- {{ partner }}
{% endfor %}

{% endif %}



{% if profile_details.additional_details and profile_details.additional_details.prototyping %}
# Additional details:

## Prototyping:
{% for detail in profile_details.additional_details.prototyping %}
- {{ detail }}
{% endfor %}

{% endif %}