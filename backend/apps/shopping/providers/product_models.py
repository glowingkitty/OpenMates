"""Provider-independent schemas retained for historical shopping embeds."""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
from backend.apps.shopping.providers.product_images import normalize_image_urls

@dataclass
class ProductAttributes:
    """Dietary and product-type flags in historical product data."""

    is_organic: bool = False
    is_vegan: bool = False
    is_vegetarian: bool = False
    is_dairy_free: bool = False
    is_gluten_free: bool = False
    is_new: bool = False
    is_regional: bool = False
    is_lowest_price: bool = False

@dataclass
class GroceryProductResult:
    """Historical grocery product pricing and metadata."""

    # Core identity
    product_id: str
    title: str
    brand: Optional[str]

    # Historical pricing
    price_cents: Optional[int]          # Current retail price in euro-cents
    was_price_cents: Optional[int]      # Regular price (if product is on sale)
    grammage: Optional[str]             # e.g. "500g (1 kg = 2,78 €)"
    deposit_cents: Optional[int]        # Pfand deposit in euro-cents

    # URLs
    purchase_url: str                  
    image_url: Optional[str]

    # Classification
    category_path: Optional[str]        # e.g. "Käse, Eier & Molkerei/Milch/"
    category_ids: list[str]

    # Dietary flags
    attributes: ProductAttributes

    # Limits
    order_limit: Optional[int]

    # Search metadata
    search_rank: int = 0
    image_urls: list[str] = field(default_factory=list)

    def price_eur(self) -> Optional[str]:
        """Return formatted price like '1,39 €' or None if unavailable."""
        if self.price_cents is None:
            return None
        return f"{self.price_cents / 100:.2f} €".replace(".", ",")

    def to_result_dict(self) -> dict[str, Any]:
        """
        Return a JSON-serialisable dict suitable for the skill response.

        Field names match what the frontend ShoppingSearchEmbedPreview expects.
        """
        d = asdict(self)
        d["image_urls"] = normalize_image_urls([self.image_url, *self.image_urls])
        # Add human-readable price
        d["price_eur"] = self.price_eur()
        d["type"] = "product"
        return d

@dataclass
class FabricProductResult:
    """Historical fabric product result for shopping embed rendering."""

    product_id: str
    variation_id: Optional[str]
    title: str
    brand: Optional[str]
    price: Optional[str]
    price_amount: Optional[float]
    base_price: Optional[str]
    currency: Optional[str]
    unit: Optional[str]
    stock: Optional[float]
    availability: Optional[str]
    is_salable: bool
    purchase_url: str
    image_url: Optional[str]
    category_path: Optional[str]
    category_ids: list[str]
    attributes: dict[str, Any]
    color_child_item_ids: list[str]
    search_rank: int = 0
    image_urls: list[str] = field(default_factory=list)

    def to_result_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["image_urls"] = normalize_image_urls([self.image_url, *self.image_urls])
        data["type"] = "product"
        data["price_eur"] = data["price"]
        return data

@dataclass
class MarketplaceProductResult:
    """Historical marketplace product result for shopping embed rendering."""

    title: str
    purchase_url: Optional[str]
    image_url: Optional[str]
    price: Optional[str]
    price_amount: Optional[float]
    old_price: Optional[str]
    old_price_amount: Optional[float]
    currency_symbol: Optional[str]
    asin: Optional[str]
    rating: Optional[float]
    reviews: Optional[int]
    prime: Optional[bool]
    delivery: List[str]
    bought_last_month: Optional[str]
    sponsored: Optional[bool]
    total_result_count: int
    image_urls: List[str] = field(default_factory=list)

    def to_result_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["image_urls"] = normalize_image_urls([self.image_url, *self.image_urls])
        data["type"] = "product"
        # Keep compatibility with existing shopping fullscreen sale logic.
        data["price_eur"] = data["price"]
        return data

