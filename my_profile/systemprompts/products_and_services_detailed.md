{% if profile_details.products_and_services and bot.product_details %}
# Products and services:

{% for product in profile_details.products_and_services %}

## {{ product.name }}

{% if product.type and "type" in bot.product_details %}
**Type:** {{ product.type }}
{% endif %}

{% if product.description and "description" in bot.product_details %}
**Description:** {{ product.description }}
{% endif %}

{% if product.public and "public" in bot.product_details %}
**Public:** {% if product.public %}'{{ product.name }}' can be discussed with everyone {% else %}'{{ product.name }}' is still a secret! Can only be discussed internally and with trusted individuals!{% endif %}
{% endif %}

{% if product.look and "look" in bot.product_details %}
**How '{{ product.name }}' looks like:**
{% for detail in product.look %}
- {{ detail }}
{% endfor %}
{% endif %}

{% if product.used_tech and "used_tech" in bot.product_details %}
**Used tech:**
{% for tech in product.used_tech %}
- {{ tech }}
{% endfor %}
{% endif %}

{% if product.highlights and "highlights" in bot.product_details %}
**Highlight features:**
{% for highlight in product.highlights %}
- {{ highlight }}
{% endfor %}
{% endif %}

{% if product.website and "website" in bot.product_details %}
**Website:** {{ product.website }}
{% endif %}

{% if product.stage and "stage" in bot.product_details %}
**Stage:** {{ product.stage }}
{% endif %}

{% if product.price and "price" in bot.product_details %}
**Price:** {{ product.price }}{% if product.currency and "currency" in bot.product_details %} {{ product.currency }}{% endif %}{% if product.payment_type and "payment_type" in bot.product_details %} ({{ product.payment_type }}){% endif %}
{% endif %}

{% endfor %}
{% endif %}