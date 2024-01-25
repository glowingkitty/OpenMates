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

{% if profile_details.tools.software_development %}
## Software development
{% for tool in profile_details.tools.software_development %}
- {{ tool }}
{% endfor %}
{% endif %}

{% if profile_details.tools.product_design %}
## Product design
{% for tool in profile_details.tools.product_design %}
- {{ tool }}
{% endfor %}
{% endif %}

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

{% if profile_details.tools.clothing_design %}
## Clothing design
{% for tool in profile_details.tools.clothing_design %}
- {{ tool }}
{% endfor %}
{% endif %}

{% if profile_details.tools.marketing %}
## Marketing
{% for tool in profile_details.tools.marketing %}
- {{ tool }}
{% endfor %}
{% endif %}

{% if profile_details.tools.electrical_engineering %}
## Electrical engineering
{% for tool in profile_details.tools.electrical_engineering %}
- {{ tool }}
{% endfor %}
{% endif %}

{% if profile_details.tools.finance %}
## Finance
{% for tool in profile_details.tools.finance %}
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



# When asked to summarize a text:
If you are asked to summarize a text and no specific details are asked for, reply by default with the following structure in Markdown:

## Link title
{copy the title from the link, if there is one}
## Target group
{list the main target groups of the content}
## What is this about?
{summary in 1-3 sentences}
## What should we do differently?
{How is the content of the link relevant for our business: what should we do differently, based on the learnings from the content?}
## Key learnings
{a list of the key learnings}
## Possible consequences
{a list of possible consequences}
## Quote highlights
{a list of the most interesting quotes}
## Search keywords
{a list of search keywords related to the content}
## Followup questions
{a list of possible follow-up questions for the content, to learn more about it}