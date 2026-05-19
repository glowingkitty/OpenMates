"""
Regression tests for the shopping search Stoffe.de provider integration.

These tests stay at the parser/routing boundary so they do not depend on the
live Stoffe.de storefront during regular backend test runs. Network behavior is
covered by manual provider smoke tests and deployed API verification.
"""

import sys
import types

from backend.apps.shopping.providers.stoffe_provider import _parse_product

sanitizer_stub = types.ModuleType(
    "backend.apps.ai.processing.external_result_sanitizer"
)


async def _sanitize_long_text_fields_in_payload(payload, **_kwargs):
    return payload


sanitizer_stub.sanitize_long_text_fields_in_payload = _sanitize_long_text_fields_in_payload
sys.modules.setdefault(
    "backend.apps.ai.processing.external_result_sanitizer",
    sanitizer_stub,
)

celery_stub = types.ModuleType("celery")
celery_stub.Celery = object
sys.modules.setdefault("celery", celery_stub)


def _get_search_products_skill_class():
    from backend.apps.shopping.skills.search_products import SearchProductsSkill

    return SearchProductsSkill


def test_stoffe_parse_product_extracts_fabric_fields():
    raw = {
        "item": {
            "id": 68087512,
            "manufacturer": {"externalName": "Snaply"},
            "free1": "[68087513,68087514]",
        },
        "variation": {
            "id": 112466,
            "availability": {
                "names": {"name": "Sofort versandfertig, Lieferzeit 2-4 Werktage"}
            },
        },
        "texts": {
            "name1": "Baumwoll-Musselin - Double Gauze Bestickt Zitronen Weiß",
            "urlPath": "baumwoll-musselin-zitronen-weiss",
        },
        "prices": {
            "default": {
                "price": {"value": 15.19, "formatted": "15,19 €"},
                "basePrice": "15,19 € / Meter",
                "currency": "EUR",
            }
        },
        "unit": {"names": {"name": "Meter"}},
        "stock": {"net": 20.5},
        "filter": {"isSalable": True},
        "images": {"all": [{"urlPreview": "https://example.test/fabric.jpg"}]},
        "ids": {"categories": {"branches": [13701]}},
        "variationProperties": [
            {
                "properties": [
                    {"names": {"name": "Baumwolle %"}, "values": {"value": "100"}},
                    {"names": {"name": "Stoffbreite (cm)"}, "values": {"value": "130"}},
                    {"names": {"name": "Name 1"}, "values": {"value": "Zitronen Musselin"}},
                    {"names": {"name": "URL"}, "values": {"value": "zitronen-musselin"}},
                ]
            }
        ],
    }

    product = _parse_product(raw, rank=1).to_result_dict()

    assert product["product_id"] == "68087512"
    assert product["variation_id"] == "112466"
    assert product["title"] == "Zitronen Musselin"
    assert product["brand"] == "Snaply"
    assert product["price"] == "15,19 €"
    assert product["price_eur"] == "15,19 €"
    assert product["price_amount"] == 15.19
    assert product["base_price"] == "15,19 € / Meter"
    assert product["unit"] == "Meter"
    assert product["stock"] == 20.5
    assert product["is_salable"] is True
    assert product["availability"] == "Sofort versandfertig, Lieferzeit 2-4 Werktage"
    assert product["purchase_url"] == "https://www.stoffe.de/zitronen-musselin/a-68087512/"
    assert product["color_child_item_ids"] == ["68087513", "68087514"]
    assert product["attributes"]["Baumwolle %"] == "100"


def test_shopping_category_routes_to_stoffe_when_provider_omitted():
    SearchProductsSkill = _get_search_products_skill_class()
    provider, error = SearchProductsSkill._resolve_provider(None, "fabrics")

    assert error is None
    assert provider == SearchProductsSkill.STOFFE_PROVIDER


def test_shopping_category_schema_exposes_enum_values():
    from backend.apps.shopping.skills.search_products import SearchProductsRequestItem

    schema = SearchProductsRequestItem.model_json_schema()

    category_schema = schema["properties"]["category"]
    category_options = category_schema.get("anyOf") or []
    enum_values = next(option["enum"] for option in category_options if "enum" in option)
    assert "fabrics" in enum_values
    assert "sewing_supplies" in enum_values
    assert "grocery" in enum_values


def test_shopping_category_allows_fabrics_on_amazon():
    SearchProductsSkill = _get_search_products_skill_class()
    provider, error = SearchProductsSkill._resolve_provider("Amazon", "fabrics")

    assert error is None
    assert provider == SearchProductsSkill.AMAZON_PROVIDER


def test_shopping_category_rejects_groceries_on_stoffe():
    SearchProductsSkill = _get_search_products_skill_class()
    provider, error = SearchProductsSkill._resolve_provider("Stoffe.de", "grocery")

    assert provider == SearchProductsSkill.STOFFE_PROVIDER
    assert error is not None
    assert "cannot search category 'grocery'" in error


def test_shopping_country_routes_unsupported_rewe_country_to_amazon_when_provider_omitted():
    SearchProductsSkill = _get_search_products_skill_class()
    provider, error = SearchProductsSkill._resolve_provider(None, "grocery", "US")

    assert error is None
    assert provider == SearchProductsSkill.AMAZON_PROVIDER


def test_shopping_country_rejects_explicit_rewe_outside_germany():
    SearchProductsSkill = _get_search_products_skill_class()
    provider, error = SearchProductsSkill._resolve_provider("REWE", "grocery", "US")

    assert provider == SearchProductsSkill.REWE_PROVIDER
    assert error is not None
    assert "does not support destination country 'US'" in error


def test_shopping_country_allows_stoffe_supported_european_destination():
    SearchProductsSkill = _get_search_products_skill_class()
    provider, error = SearchProductsSkill._resolve_provider(None, "fabrics", "AT")

    assert error is None
    assert provider == SearchProductsSkill.STOFFE_PROVIDER


def test_shopping_country_routes_unsupported_stoffe_country_to_amazon_when_provider_omitted():
    SearchProductsSkill = _get_search_products_skill_class()
    provider, error = SearchProductsSkill._resolve_provider(None, "fabrics", "US")

    assert error is None
    assert provider == SearchProductsSkill.AMAZON_PROVIDER
