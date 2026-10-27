"""Provider-independent gallery normalization."""
# contract-test-file: infrastructure
from backend.apps.shopping.providers.product_images import normalize_image_urls

def test_image_urls_skip_duplicates_and_unusable_entries_in_order():
    assert normalize_image_urls([
        None, 42, "", "javascript:alert(1)", "file:///tmp/image.png", "https://",
        "https://[invalid", " https://example.test/front.jpg ",
        "https://example.test/back.jpg", "https://example.test/front.jpg",
    ]) == ["https://example.test/front.jpg", "https://example.test/back.jpg"]


def test_historical_marketplace_gallery_preserves_primary_and_prices():
    from backend.apps.shopping.providers.product_models import MarketplaceProductResult
    product = MarketplaceProductResult(
        title="Synthetic product", purchase_url="https://example.test/item",
        image_url="https://example.test/front.jpg", price="12.00 EUR", price_amount=12,
        old_price=None, old_price_amount=None, currency_symbol="EUR", asin=None,
        rating=None, reviews=None, prime=None, delivery=[], bought_last_month=None,
        sponsored=None, total_result_count=1,
        image_urls=["https://example.test/front.jpg", "https://example.test/back.jpg"],
    ).to_result_dict()
    assert product["image_urls"] == ["https://example.test/front.jpg", "https://example.test/back.jpg"]
    assert product["price_eur"] == "12.00 EUR" and product["price_amount"] == 12
    assert product["type"] == "product"
