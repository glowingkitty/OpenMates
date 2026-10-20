---
status: active
doc_type: guide
audience:
  - end-users
last_verified: 2026-10-20
claims:
  - id: user-guide-apps-shopping-source
    type: unit
    claim: The Shopping app guide is grounded in the Shopping app metadata.
    file: scripts/tests/test_user_guide_app_docs_claims.py
    assertion: user-guide-apps-shopping-source
---

# Shopping

> Search for products on REWE, Amazon and Stoffe.de with live prices.

## What It Does

The Shopping app searches for products across online stores and shows you results with real-time prices, ratings, and direct purchase links.

**Available skills:**

- **Search Products** -- Search for products on REWE (German supermarket), Amazon or Stoffe.de. Returns product names, prices, supplied product photos, and links to buy.

**Supported stores:**

- **REWE** -- German supermarket with delivery and click-and-collect options. Includes market-specific pricing. You can sort by relevance, price (low to high or high to low), or newest products.
- **Amazon** -- Marketplace products across many countries and categories (electronics, books, home, fashion, and many more). Supports filtering by department, price range, and various sort options including best sellers and review ranking.
- **Stoffe.de** -- Fabric by the meter, sewing supplies and sewing patterns, with product details and supplied gallery photos.

## How to Use It

- Search groceries: "Find organic yoghurt on REWE"
- Compare prices: "Search for coffee grinders on Amazon, sorted by price"
- Browse a category: "Show me the best-selling wireless headphones on Amazon"
- Filter results: "Find books about machine learning under 30 euros on Amazon Germany"
- Match a reference: Upload up to three fabric photos and ask, "Find cotton fabric with a similar small floral pattern and dark blue background."

## Search Using Reference Images

Attach up to three images, or refer to images your mate generated earlier in the chat.
Describe what should match, such as the pattern, colors, shape or style. Your mate
passes the exact image references to Shopping and compares product photos together
with the available product text and attributes. Results keep their prices and purchase
links; clearly conflicting or weak matches are filtered out.

When your description already supplies the search query, your mate can send the
references directly to Shopping. It does not need to view the photos first.
Viewing is useful when you ask your mate to describe an image or identify a
photo-only subject before searching.

Similarity is an estimate. It does not prove that a product is identical to your
reference or establish a fabric's composition, dimensions or quality when the store
does not state those facts. If an image cannot be read or comparison is unavailable,
Shopping marks those products as unavailable for visual comparison. Your mate should
explain that they have not been visually verified.

Shopping keeps all gallery URLs supplied by the store in `image_urls`, with
`image_url` as the primary photo. Open a product to browse its supplied photos
using the thumbnails or keyboard arrow keys. To bound comparison time and cost, it evaluates
up to forty products and the first three supplied photos per product, then keeps
your requested final result limit. Stores may supply fewer candidates. It does not
fetch extra paid Amazon product details for more photos; Amazon search often
supplies only one thumbnail. It does not use a separate image search to create
shopping results.

Authenticated API and CLI callers can pass their own uploaded image embed UUIDs
in `reference_images` inside a search request. In assistant chats the same field
uses the exact uploaded or generated `embed_ref` names. Raw image URLs and base64
are not accepted as references. More than three references are rejected; omitting
the field or passing `[]` keeps ordinary search behavior.

```json
{
  "requests": [{
    "query": "cotton floral fabric",
    "provider": "Stoffe.de",
    "category": "fabrics",
    "max_results": 5,
    "relevance_criteria": "Small floral pattern on dark blue, similar to the reference",
    "reference_images": ["YOUR_OWN_UPLOADED_IMAGE_EMBED_UUID"]
  }]
}
```

Each result group exposes `visual_evaluation.status` (`evaluated`, `partial` or
`unavailable`) and each product exposes `visual_match.status`. An evaluated product
also includes its similarity `score` from zero to four and `product_image_count`.
The score is always out of four; it is not a star rating or a probability.
Products scoring below two are removed. A product marked `unavailable` may still be
returned, but its appearance was not verified. These statuses remain meaningful even
when no products pass the comparison.

## Screenshots

![Product search results](../../images/user-guide/apps/shopping/previews/search/finished.jpg)

## Tips

- REWE results include local pricing for the Berlin area by default.
- Amazon searches can be targeted to specific country marketplaces (Germany, US, UK, France, and many more).
- Results appear as preview cards with product images and prices. Click to see more details or open the product page.
- Your mate automatically picks the right store based on what you are looking for (groceries go to REWE, electronics go to Amazon).

## Related

- [Web](./web.md) -- General web search for product reviews and comparisons
- [Maps](./maps.md) -- Find nearby physical stores
