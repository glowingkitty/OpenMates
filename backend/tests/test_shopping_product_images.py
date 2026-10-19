"""Shopping gallery regression tests with synthetic provider search responses.

These exercise provider parsing and serialization without external calls.
Each supplied photo must survive once, in order, alongside the legacy primary
image and the existing product identity, price and purchase link.
"""
# contract-test-file: infrastructure

import pytest

from backend.apps.shopping.providers.product_images import normalize_image_urls
from backend.apps.shopping.providers.rewe_provider import _parse_product as parse_rewe
from backend.apps.shopping.providers.stoffe_provider import _parse_product as parse_stoffe


def test_image_urls_skip_duplicates_and_unusable_entries_in_order():
    assert normalize_image_urls([
        None, 42, "", "javascript:alert(1)", "file:///tmp/image.png", "https://",
        "https://[invalid", " https://example.test/front.jpg ",
        "https://example.test/back.jpg", "https://example.test/front.jpg",
    ]) == ["https://example.test/front.jpg", "https://example.test/back.jpg"]


def test_rewe_retains_gallery_and_fallback_with_price_and_purchase_url():
    raw = {
        "id": "12345",
        "productName": "Synthetic yoghurt",
        "_links": {"detail": {"href": "/p/synthetic-yoghurt/12345"}},
        "media": {"images": [
            {"_links": {"self": {"href": "https://example.test/front.png"}}},
            {"_links": {"self": {"href": "https://example.test/ingredients.png"}}},
            {"_links": {"self": {"href": "https://example.test/front.png"}}},
            None, {}, {"_links": None},
        ]},
        "imageURL": "https://example.test/packaging.png",
        "_embedded": {"articles": [{"_embedded": {"listing": {"pricing": {
            "currentRetailPrice": 139, "regularRetailPrice": 169,
        }}}}]},
    }
    product = parse_rewe(raw, rank=2).to_result_dict()
    assert product["image_url"] == "https://example.test/front.png"
    assert product["image_urls"] == [
        "https://example.test/front.png",
        "https://example.test/ingredients.png",
        "https://example.test/packaging.png",
    ]
    assert product["product_id"] == "12345"
    assert product["price_eur"] == "1,39 €"
    assert product["was_price_cents"] == 169
    assert product["purchase_url"] == "https://shop.rewe.de/p/synthetic-yoghurt/12345"


@pytest.mark.parametrize("parse", [parse_rewe, parse_stoffe])
def test_products_without_images_have_empty_gallery(parse):
    product = parse({}, rank=1).to_result_dict()
    assert product["image_url"] is None
    assert product["image_urls"] == []


def test_rewe_legacy_image_fallback_and_constructed_product_compatibility():
    product = parse_rewe({"media": None, "imageURL": "https://example.test/front.png"}, rank=1)
    assert product.image_url == "https://example.test/front.png"
    assert product.image_urls == [product.image_url]
    product.image_urls = []  # Older callers can still construct a primary-only product.
    assert product.to_result_dict()["image_urls"] == [product.image_url]
