/**
 * Preview mock data for ShoppingSearchEmbedFullscreen (shopping/search_products skill result).
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/shopping
 */

const sampleResults = [
  {
    product_id: "rewe-12345",
    title: "Bio Vollmilch-Joghurt Naturell",
    brand: "Weihenstephan",
    price_cents: 139,
    price_eur: "1,39 €",
    grammage: "500g (0,28 €/100g)",
    purchase_url: "https://shop.rewe.de/p/weihenstephan-bio-joghurt/12345",
    image_url: null,
    attributes: { is_organic: true },
  },
  {
    product_id: "rewe-12346",
    title: "Demeter Bio-Joghurt mild",
    brand: "Andechser Natur",
    price_cents: 249,
    price_eur: "2,49 €",
    grammage: "500g (0,50 €/100g)",
    purchase_url: "https://shop.rewe.de/p/andechser-demeter-joghurt/12346",
    image_url: null,
    attributes: { is_organic: true, is_vegetarian: true },
  },
  {
    product_id: "rewe-12347",
    title: "Griechischer Joghurt 10% Fett",
    brand: "REWE Bio",
    price_cents: 189,
    price_eur: "1,89 €",
    grammage: "400g (0,47 €/100g)",
    purchase_url: "https://shop.rewe.de/p/rewe-bio-griechischer-joghurt/12347",
    image_url: null,
    attributes: { is_organic: true, is_vegetarian: true },
  },
  {
    product_id: "rewe-12348",
    title: "Skyr Natur 0,2% Fett",
    brand: "REWE Beste Wahl",
    price_cents: 99,
    price_eur: "0,99 €",
    grammage: "450g (0,22 €/100g)",
    purchase_url: "https://shop.rewe.de/p/rewe-skyr-natur/12348",
    image_url: null,
    attributes: { is_vegetarian: true },
  },
];

/** Default props — shows a finished shopping search fullscreen with results */
const defaultProps = {
  query: "bio joghurt",
  provider: "REWE",
  status: "finished" as const,
  results: sampleResults,
  onClose: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Processing state — searching */
  processing: {
    query: "wireless headphones",
    provider: "Amazon",
    status: "processing" as const,
    results: [],
  },

  /** Error state */
  error: {
    query: "bio joghurt",
    provider: "REWE",
    status: "error" as const,
    results: [],
  },

  /** Amazon results */
  amazon: {
    query: "noise cancelling headphones",
    provider: "Amazon",
    status: "finished" as const,
    results: [
      {
        asin: "B0CH7DL6JW",
        title: "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
        brand: "Sony",
        price: "279.00",
        price_amount: 279.0,
        currency_symbol: "€",
        rating: 4.7,
        reviews: 3842,
        prime: true,
        image_url: null,
        purchase_url: "https://www.amazon.de/dp/B0CH7DL6JW",
      },
      {
        asin: "B09JQS53RZ",
        title: "Bose QuietComfort 45 Bluetooth Wireless Headphones",
        brand: "Bose",
        price: "249.00",
        price_amount: 249.0,
        currency_symbol: "€",
        rating: 4.6,
        reviews: 2156,
        prime: true,
        image_url: null,
        purchase_url: "https://www.amazon.de/dp/B09JQS53RZ",
      },
      {
        asin: "B09JQS53RX",
        title: "Apple AirPods Max Wireless Over-Ear Headphones",
        brand: "Apple",
        price: "499.00",
        price_amount: 499.0,
        currency_symbol: "€",
        rating: 4.5,
        reviews: 1204,
        prime: false,
        image_url: null,
        purchase_url: "https://www.amazon.de/dp/B09JQS53RX",
      },
    ],
  },

  /** Mobile view */
  mobile: {
    ...defaultProps,
    isMobile: true,
  },
};
