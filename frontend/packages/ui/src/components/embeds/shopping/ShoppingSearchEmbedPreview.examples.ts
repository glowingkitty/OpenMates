/**
 * App-store examples for the shopping skill.
 *
 * Captured from real REWE product search responses, trimmed to 4 products per query.
 */

export interface ShoppingSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: ShoppingSearchStoreExample[] = [
  {
    "id": "store-example-shopping-search-products-1",
    "query": "Bio dark chocolate",
    "query_translation_key": "settings.app_store_examples.shopping.search_products.1",
    "provider": "REWE",
    "status": "finished",
    "results": [
      {
        "product_id": "1006852",
        "title": "REWE Bio Edelvollmilch-Schokolade 100g",
        "brand": "REWE Bio",
        "image_url": "https://img.rewe-static.de/1006852/9584790_digital-image.png",
        "purchase_url": "https://shop.rewe.de/p/rewe-bio-edelvollmilch-schokolade-100g/1006852",
        "category_path": "Süßes & Salziges/Schokolade/Tafelschokolade/Vollmilch-Schokolade/",
        "provider": "REWE"
      },
      {
        "product_id": "1168942",
        "title": "Gepa Bio Mandel-Orange Schokolade Noir 100g",
        "brand": "Gepa",
        "image_url": "https://img.rewe-static.de/1168942/14206770_digital-image.png",
        "purchase_url": "https://shop.rewe.de/p/gepa-bio-mandel-orange-schokolade-noir-100g/1168942",
        "category_path": "Süßes & Salziges/Schokolade/Tafelschokolade/Nuss-Schokolade/",
        "provider": "REWE"
      },
      {
        "product_id": "3009709",
        "title": "REWE Bio Edel-Bitter-Schokolade 85% 100g",
        "brand": "REWE Bio",
        "image_url": "https://img.rewe-static.de/3009709/26210056_digital-image.png",
        "purchase_url": "https://shop.rewe.de/p/rewe-bio-edel-bitter-schokolade-85-100g/3009709",
        "category_path": "Süßes & Salziges/Schokolade/Tafelschokolade/Zartbitter-Schokolade/",
        "provider": "REWE"
      },
      {
        "product_id": "8572345",
        "title": "Gepa Bio Naturland Lemon Crisp Schokolade 80g",
        "brand": "Gepa",
        "image_url": "https://img.rewe-static.de/8572345/35138618_digital-image.png",
        "purchase_url": "https://shop.rewe.de/p/gepa-bio-naturland-lemon-crisp-schokolade-80g/8572345",
        "category_path": "Süßes & Salziges/Schokolade/Tafelschokolade/Zartbitter-Schokolade/",
        "provider": "REWE"
      }
    ]
  },
  {
    "id": "store-example-shopping-search-products-2",
    "query": "Extra virgin olive oil",
    "query_translation_key": "settings.app_store_examples.shopping.search_products.2",
    "provider": "REWE",
    "status": "finished",
    "results": [
      {
        "product_id": "9895756",
        "title": "Olivenöl Extra Vergine 1000ml",
        "image_url": "https://img.rewe-static.de/9895756/48822830_digital-image.png",
        "purchase_url": "https://shop.rewe.de/p/olivenoel-extra-vergine-1000ml/9895756",
        "category_path": "Öle, Soßen & Gewürze/Öle/Olivenöl/",
        "provider": "REWE"
      },
      {
        "product_id": "2826640",
        "title": "Bertolli Extra Vergine Robusto würzig 500ml",
        "brand": "Bertolli",
        "image_url": "https://img.rewe-static.de/2826640/20867635_digital-image.png",
        "purchase_url": "https://shop.rewe.de/p/bertolli-extra-vergine-robusto-wuerzig-500ml/2826640",
        "category_path": "Öle, Soßen & Gewürze/Öle/Olivenöl/",
        "provider": "REWE"
      },
      {
        "product_id": "3308580",
        "title": "Ghorban Bio Olio Extra Vergine di Oliva 500ml",
        "image_url": "https://img.rewe-static.de/3308580/28120803_digital-image.png",
        "purchase_url": "https://shop.rewe.de/p/ghorban-bio-olio-extra-vergine-di-oliva-500ml/3308580",
        "category_path": "Öle, Soßen & Gewürze/Öle/Olivenöl/",
        "provider": "REWE"
      },
      {
        "product_id": "2047909",
        "title": "Ghorban Bio Olivenöl Olio Extra Vergine Di Olivia 250ml",
        "image_url": "https://img.rewe-static.de/2047909/29208351_digital-image.png",
        "purchase_url": "https://shop.rewe.de/p/ghorban-bio-olivenoel-olio-extra-vergine-di-olivia-250ml/2047909",
        "category_path": "Öle, Soßen & Gewürze/Öle/Olivenöl/",
        "provider": "REWE"
      }
    ]
  },
  {
    "id": "store-example-shopping-search-products-3",
    "query": "Spaghetti pasta",
    "query_translation_key": "settings.app_store_examples.shopping.search_products.3",
    "provider": "REWE",
    "status": "finished",
    "results": [
      {
        "product_id": "9660143",
        "title": "Bernbacher Bella Pasta Spaghetti XXL 1kg",
        "brand": "Bernbacher",
        "image_url": "https://img.rewe-static.de/9660143/24301440_digital-image.png",
        "purchase_url": "https://shop.rewe.de/p/bernbacher-bella-pasta-spaghetti-xxl-1kg/9660143",
        "category_path": "Fertiggerichte & Konserven/Gekühlte Nudeln & Teigwaren/Frische Pasta/",
        "provider": "REWE"
      },
      {
        "product_id": "5233046",
        "title": "Pasta Sassella Spaghettini 500g",
        "image_url": "https://img.rewe-static.de/5233046/32754186_digital-image.png",
        "purchase_url": "https://shop.rewe.de/p/pasta-sassella-spaghettini-500g/5233046",
        "category_path": "Fertiggerichte & Konserven/Gekühlte Nudeln & Teigwaren/Frische Pasta/",
        "provider": "REWE"
      },
      {
        "product_id": "8219291",
        "title": "Giovanni Rana Spaghetti 250g",
        "brand": "Giovanni Rana",
        "image_url": "https://img.rewe-static.de/8219291/31378818_digital-image.png",
        "purchase_url": "https://shop.rewe.de/p/giovanni-rana-spaghetti-250g/8219291",
        "category_path": "Fertiggerichte & Konserven/Gekühlte Nudeln & Teigwaren/Frische Pasta/",
        "provider": "REWE"
      },
      {
        "product_id": "720372",
        "title": "Zabler Hochzeit Nudeln Spaghetti 250g",
        "brand": "Zabler",
        "image_url": "https://img.rewe-static.de/0720372/2532500_digital-image.png",
        "purchase_url": "https://shop.rewe.de/p/zabler-hochzeit-nudeln-spaghetti-250g/720372",
        "category_path": "Kochen & Backen/Nudeln/Lange Pasta/",
        "provider": "REWE"
      }
    ]
  }
]

export default examples;
