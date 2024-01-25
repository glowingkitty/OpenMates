{% if profile_details.products_and_services %}
# Products and services:
{% for product in profile_details.products_and_services %}
- {{ product.name }}{% if product.type %} ({{ product.type }}){% endif %}: {{ product.description }}{% endfor %}
{% endif %}