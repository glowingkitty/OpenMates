{ start_for_all.md }
{ profile_details_for_all.md }
{ products_and_services_detailed.md }
{ updates_milestones_prograstination.md }



{% if profile_details.tools and profile_details.tools.product_design %}
# Tools we use, for:

## Product design
{% for tool in profile_details.tools.product_design %}
- {{ tool }}
{% endfor %}

{% endif %}



{% if profile_details.relevant_topics and profile_details.relevant_topics.product_design %}
# Topics that are relevant for us:

## Product design
{% for topic in profile_details.relevant_topics.product_design %}
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

## Business:
{% for detail in profile_details.additional_details.business %}
- {{ detail }}
{% endfor %}

{% endif %}