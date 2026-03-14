/**
 * frontend/packages/ui/src/components/embeds/shopping/ShoppingResultEmbedFullscreen.preview.ts
 *
 * Mock props for ShoppingResultEmbedFullscreen child overlay.
 * Architecture context: docs/architecture/embeds.md.
 * Verification reference: frontend/apps/web_app/tests/embed-showcase.spec.ts.
 * Access path: /dev/preview/embeds/shopping/ShoppingResultEmbedFullscreen.
 */

const defaultProps = {
  product: {
    embed_id: "preview-shopping-result-fs-1",
    product_id: "rewe-12345",
    title: "Bio Vollmilch-Joghurt Naturell",
    brand: "Weihenstephan",
    price_cents: 139,
    price_eur: "1,39 €",
    was_price_cents: 179,
    grammage: "500g (0,28 €/100g)",
    purchase_url: "https://shop.rewe.de/p/weihenstephan-bio-joghurt/12345",
    image_url: null,
    category_path: "Molkereiprodukte > Joghurt",
    rating: 4.6,
    reviews: 832,
    prime: false,
    delivery: ["Lieferung heute"],
    bought_last_month: "500+ mal im letzten Monat gekauft",
    provider: "REWE",
    attributes: {
      is_organic: true,
      is_vegetarian: true,
      is_regional: true,
    },
  },
  onClose: () => {},
};

export default defaultProps;

export const variants = {
  amazon: {
    product: {
      embed_id: "preview-shopping-result-fs-amazon",
      asin: "B0CH7DL6JW",
      title: "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
      brand: "Sony",
      price: "€279.00",
      price_amount: 279,
      old_price_amount: 329,
      currency_symbol: "€",
      purchase_url: "https://www.amazon.de/dp/B0CH7DL6JW",
      image_url: null,
      rating: 4.7,
      reviews: 3842,
      prime: true,
      delivery: ["KOSTENLOSE Lieferung bis morgen"],
      bought_last_month: "2K+ bought in past month",
      provider: "Amazon",
      country: "DE",
      attributes: { is_new: true },
    },
    onClose: () => {},
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },
  noPrice: {
    product: {
      embed_id: "preview-shopping-result-fs-no-price",
      title: "Produkt ohne Preisangabe",
      brand: "Unknown Brand",
      purchase_url: "https://shop.rewe.de/",
      image_url: null,
      provider: "REWE",
    },
    onClose: () => {},
  },
};
