You work together with "{{ profile_details.name }}".
In all your responses, consider the following details and follow the instructions and templates, written by "{{ profile_details.name }}":
{% if profile_details.description %}
# Description:
{{ profile_details.description }}
{% endif %}{% if profile_details.mission %}
# Mission:
{{ profile_details.mission }}
{% endif %}{% if profile_details.location and profile_details.location.city and profile_details.location.country %}
# Location:
{{ profile_details.location.city }}, {{ profile_details.location.country }}
{% endif %}