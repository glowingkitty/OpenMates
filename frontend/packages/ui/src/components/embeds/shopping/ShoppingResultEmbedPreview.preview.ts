/**
 * frontend/packages/ui/src/components/embeds/shopping/ShoppingResultEmbedPreview.preview.ts
 *
 * Mock props for a single shopping result card shown inside search grids.
 * Architecture context: docs/architecture/embeds.md.
 * Verification reference: frontend/apps/web_app/tests/embed-showcase.spec.ts.
 * Access path: /dev/preview/embeds/shopping/ShoppingResultEmbedPreview.
 */

const defaultProps = {
  id: "preview-shopping-result-1",
  title: "Bio Vollmilch-Joghurt Naturell",
  brand: "Weihenstephan",
  price_cents: 139,
  price_eur: "1,39 €",
  was_price_cents: 179,
  grammage: "500g (0,28 €/100g)",
  image_url: null,
  attributes: { is_organic: true, is_vegetarian: true },
  rating: 4.6,
  reviews: 832,
  prime: false,
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  amazon: {
    id: "preview-shopping-result-amazon",
    title: "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
    brand: "Sony",
    price: "€279.00",
    price_amount: 279,
    old_price_amount: 329,
    currency_symbol: "€",
    image_url: null,
    rating: 4.7,
    reviews: 3842,
    prime: true,
    attributes: { is_new: true },
    status: "finished" as const,
    isMobile: false,
    onFullscreen: () => {},
  },
  stoffe: {
    id: "preview-shopping-result-stoffe",
    title: "Baumwoll-Musselin - Double Gauze Bestickt Zitronen Weiß",
    brand: "Snaply",
    price: "15,19 €",
    price_eur: "15,19 €",
    price_amount: 15.19,
    base_price: "15,19 € / Meter",
    stock: 20.5,
    availability: "Sofort versandfertig, Lieferzeit 2-4 Werktage",
    color_child_item_ids: ["68087513", "68087514"],
    image_url: null,
    attributes: {
      "Baumwolle %": "100",
      "Stoffbreite (cm)": "130",
      Motiv: "Zitronen",
    },
    status: "finished" as const,
    isMobile: false,
    onFullscreen: () => {},
  },
  noPrice: {
    ...defaultProps,
    id: "preview-shopping-result-no-price",
    price_cents: null,
    price_eur: null,
    was_price_cents: null,
    price: null,
    price_amount: null,
    old_price_amount: null,
  },
  mobile: {
    ...defaultProps,
    id: "preview-shopping-result-mobile",
    isMobile: true,
  },
};
