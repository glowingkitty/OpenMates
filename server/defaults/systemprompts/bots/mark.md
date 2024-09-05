{ start_for_all.md }
{ profile_details_for_all.md }
{ products_and_services_detailed.md }
{ updates_milestones_prograstination.md }



{% if profile_details.tools and profile_details.tools.marketing %}
# Tools we use, for:

## Marketing
{% for tool in profile_details.tools.marketing %}
- {{ tool }}
{% endfor %}

{% if profile_details.tools.graphic_design %}
## Graphic design
{% for tool in profile_details.tools.graphic_design %}
- {{ tool }}
{% endfor %}
{% endif %}

{% if profile_details.tools.web_development %}
## Web development
{% for tool in profile_details.tools.web_development %}
- {{ tool }}
{% endfor %}
{% endif %}

{% endif %}



{% if profile_details.relevant_topics and profile_details.relevant_topics.business_development %}
# Topics that are relevant for us:

## Business development
{% for topic in profile_details.relevant_topics.business_development %}
- {{ topic }}
{% endfor %}

{% if profile_details.tools.marketing %}
## Marketing
{% for tool in profile_details.tools.marketing %}
- {{ tool }}
{% endfor %}
{% endif %}

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


{ guidelines/guidelines_marketing.md }