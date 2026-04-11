/**
 * App-store examples for the shopping skill.
 *
 * Invented brand names and prices so the app store does not endorse specific supermarket products.
 *
 * These are hand-crafted synthetic fixtures. All names, addresses,
 * prices and ratings are invented so that the app store never promotes
 * specific real-world businesses, doctors, landlords or venues. The
 * shape matches the real provider response so the preview + fullscreen
 * render identically. A "Sample data" banner is shown at the top of
 * the fullscreen via the is_store_example flag set by SkillExamplesSection.
 */

export interface ShoppingSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: ShoppingSearchStoreExample[] = [
  {
    "id": "store-example-shopping-search-products-1",
    "query": "Organic dark chocolate",
    "query_translation_key": "settings.app_store_examples.shopping.search_products.1",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "product_id": "sp-1-1",
        "title": "Brightleaf Organic Dark Chocolate 70%",
        "brand": "Brightleaf",
        "price_cents": 299,
        "price_eur": "2.99",
        "grammage": "100g",
        "image_url": "",
        "purchase_url": "",
        "category_path": "Sample Data",
        "provider": "Sample Data"
      },
      {
        "product_id": "sp-1-2",
        "title": "Meadowford Bio Zartbitter 85%",
        "brand": "Meadowford",
        "price_cents": 349,
        "price_eur": "3.49",
        "grammage": "100g",
        "image_url": "",
        "purchase_url": "",
        "category_path": "Sample Data",
        "provider": "Sample Data"
      },
      {
        "product_id": "sp-1-3",
        "title": "Cacao North Single Origin 72%",
        "brand": "Cacao North",
        "price_cents": 429,
        "price_eur": "4.29",
        "grammage": "80g",
        "image_url": "",
        "purchase_url": "",
        "category_path": "Sample Data",
        "provider": "Sample Data"
      },
      {
        "product_id": "sp-1-4",
        "title": "Sample House Dark Chocolate 60%",
        "brand": "Sample House",
        "price_cents": 189,
        "price_eur": "1.89",
        "grammage": "100g",
        "image_url": "",
        "purchase_url": "",
        "category_path": "Sample Data",
        "provider": "Sample Data"
      }
    ]
  },
  {
    "id": "store-example-shopping-search-products-2",
    "query": "Extra virgin olive oil",
    "query_translation_key": "settings.app_store_examples.shopping.search_products.2",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "product_id": "sp-2-1",
        "title": "Olivara Extra Vergine Classico 500ml",
        "brand": "Olivara",
        "price_cents": 899,
        "price_eur": "8.99",
        "grammage": "500ml",
        "image_url": "",
        "purchase_url": "",
        "category_path": "Sample Data",
        "provider": "Sample Data"
      },
      {
        "product_id": "sp-2-2",
        "title": "Sample Grove Organic EVOO",
        "brand": "Sample Grove",
        "price_cents": 1199,
        "price_eur": "11.99",
        "grammage": "500ml",
        "image_url": "",
        "purchase_url": "",
        "category_path": "Sample Data",
        "provider": "Sample Data"
      },
      {
        "product_id": "sp-2-3",
        "title": "Harbor Press Cold Extracted Olive Oil 750ml",
        "brand": "Harbor Press",
        "price_cents": 1549,
        "price_eur": "15.49",
        "grammage": "750ml",
        "image_url": "",
        "purchase_url": "",
        "category_path": "Sample Data",
        "provider": "Sample Data"
      },
      {
        "product_id": "sp-2-4",
        "title": "Example Hills Italian Olivenöl",
        "brand": "Example Hills",
        "price_cents": 599,
        "price_eur": "5.99",
        "grammage": "500ml",
        "image_url": "",
        "purchase_url": "",
        "category_path": "Sample Data",
        "provider": "Sample Data"
      }
    ]
  },
  {
    "id": "store-example-shopping-search-products-3",
    "query": "Spaghetti pasta",
    "query_translation_key": "settings.app_store_examples.shopping.search_products.3",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "product_id": "sp-3-1",
        "title": "Bella Nonna Spaghetti n°5 500g",
        "brand": "Bella Nonna",
        "price_cents": 149,
        "price_eur": "1.49",
        "grammage": "500g",
        "image_url": "",
        "purchase_url": "",
        "category_path": "Sample Data",
        "provider": "Sample Data"
      },
      {
        "product_id": "sp-3-2",
        "title": "Sample Pasta Spaghetti Integrali",
        "brand": "Sample Pasta",
        "price_cents": 189,
        "price_eur": "1.89",
        "grammage": "500g",
        "image_url": "",
        "purchase_url": "",
        "category_path": "Sample Data",
        "provider": "Sample Data"
      },
      {
        "product_id": "sp-3-3",
        "title": "Grano Oro Bronze-Cut Spaghetti 500g",
        "brand": "Grano Oro",
        "price_cents": 229,
        "price_eur": "2.29",
        "grammage": "500g",
        "image_url": "",
        "purchase_url": "",
        "category_path": "Sample Data",
        "provider": "Sample Data"
      },
      {
        "product_id": "sp-3-4",
        "title": "Meadowford Organic Spaghetti",
        "brand": "Meadowford",
        "price_cents": 269,
        "price_eur": "2.69",
        "grammage": "500g",
        "image_url": "",
        "purchase_url": "",
        "category_path": "Sample Data",
        "provider": "Sample Data"
      }
    ]
  }
]

export default examples;
