/**
 * App-store examples for the nutrition search_recipes skill.
 *
 * Hand-crafted synthetic fixtures with invented recipe names so the app
 * store never endorses specific real-world recipes or brands. The shape
 * matches the real REWE provider response so the preview + fullscreen
 * render identically. A "Sample data" banner is shown at the top of
 * the fullscreen via the is_store_example flag set by SkillExamplesSection.
 */

export interface NutritionSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: NutritionSearchStoreExample[] = [
  {
    "id": "store-example-nutrition-search-recipes-1",
    "query": "Vegetarische Pasta",
    "query_translation_key": "settings.app_store_examples.nutrition.search_recipes.1",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "type": "recipe",
        "uid": "nr-1-1",
        "title": "Penne mit geröstetem Gemüse und Basilikum",
        "description": "Bunte Penne mit Paprika, Zucchini und frischem Basilikum-Pesto.",
        "image_url": "",
        "total_time_minutes": 25,
        "difficulty": "einfach",
        "rating": 4.6,
        "rating_count": 142,
        "dietary_tags": ["vegetarisch"]
      },
      {
        "type": "recipe",
        "uid": "nr-1-2",
        "title": "Spaghetti Aglio e Olio mit Spinat",
        "description": "Klassisches Knoblauch-Öl-Pasta-Gericht mit frischem Blattspinat und Chiliflocken.",
        "image_url": "",
        "total_time_minutes": 20,
        "difficulty": "einfach",
        "rating": 4.8,
        "rating_count": 219,
        "dietary_tags": ["vegetarisch", "vegan"]
      },
      {
        "type": "recipe",
        "uid": "nr-1-3",
        "title": "Rigatoni mit Auberginen-Ragout",
        "description": "Herzhafte Rigatoni mit geschmorter Aubergine, Tomaten und Parmesan.",
        "image_url": "",
        "total_time_minutes": 40,
        "difficulty": "mittel",
        "rating": 4.4,
        "rating_count": 87,
        "dietary_tags": ["vegetarisch"]
      },
      {
        "type": "recipe",
        "uid": "nr-1-4",
        "title": "Fusilli mit Ricotta und getrockneten Tomaten",
        "description": "Cremige Fusilli mit Ricotta, sonnengetrockneten Tomaten und Pinienkernen.",
        "image_url": "",
        "total_time_minutes": 15,
        "difficulty": "einfach",
        "rating": 4.3,
        "rating_count": 64,
        "dietary_tags": ["vegetarisch"]
      }
    ]
  },
  {
    "id": "store-example-nutrition-search-recipes-2",
    "query": "Schnelle Bowl Rezepte",
    "query_translation_key": "settings.app_store_examples.nutrition.search_recipes.2",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "type": "recipe",
        "uid": "nr-2-1",
        "title": "Buddha Bowl mit Quinoa und Avocado",
        "description": "Bunte Bowl mit Quinoa, Avocado, Edamame und Tahini-Dressing.",
        "image_url": "",
        "total_time_minutes": 20,
        "difficulty": "einfach",
        "rating": 4.7,
        "rating_count": 312,
        "dietary_tags": ["vegan", "glutenfrei"]
      },
      {
        "type": "recipe",
        "uid": "nr-2-2",
        "title": "Poké Bowl mit Lachs und Mango",
        "description": "Frische Poké Bowl mit mariniertem Lachs, Mango, Gurke und Sushi-Reis.",
        "image_url": "",
        "total_time_minutes": 25,
        "difficulty": "einfach",
        "rating": 4.9,
        "rating_count": 187,
        "dietary_tags": []
      },
      {
        "type": "recipe",
        "uid": "nr-2-3",
        "title": "Mexikanische Burrito Bowl",
        "description": "Würzige Bowl mit schwarzen Bohnen, Mais, Reis und Limetten-Koriander-Dressing.",
        "image_url": "",
        "total_time_minutes": 30,
        "difficulty": "einfach",
        "rating": 4.5,
        "rating_count": 156,
        "dietary_tags": ["vegetarisch"]
      },
      {
        "type": "recipe",
        "uid": "nr-2-4",
        "title": "Teriyaki-Hähnchen Bowl",
        "description": "Glasiertes Hähnchen mit Brokkoli, Edamame und Jasminreis.",
        "image_url": "",
        "total_time_minutes": 35,
        "difficulty": "mittel",
        "rating": 4.6,
        "rating_count": 98,
        "dietary_tags": []
      }
    ]
  },
  {
    "id": "store-example-nutrition-search-recipes-3",
    "query": "Low Carb Abendessen",
    "query_translation_key": "settings.app_store_examples.nutrition.search_recipes.3",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "type": "recipe",
        "uid": "nr-3-1",
        "title": "Zucchini-Nudeln mit Garnelen",
        "description": "Leichte Zoodles mit Knoblauch-Garnelen und Cherry-Tomaten.",
        "image_url": "",
        "total_time_minutes": 20,
        "difficulty": "einfach",
        "rating": 4.8,
        "rating_count": 245,
        "dietary_tags": ["low-carb", "glutenfrei"]
      },
      {
        "type": "recipe",
        "uid": "nr-3-2",
        "title": "Blumenkohl-Pizza mit Mozzarella",
        "description": "Knuspriger Blumenkohlboden mit Tomatensauce, Mozzarella und frischen Kräutern.",
        "image_url": "",
        "total_time_minutes": 45,
        "difficulty": "mittel",
        "rating": 4.3,
        "rating_count": 178,
        "dietary_tags": ["low-carb", "vegetarisch", "glutenfrei"]
      },
      {
        "type": "recipe",
        "uid": "nr-3-3",
        "title": "Lachs mit Brokkoli und Zitronenbutter",
        "description": "Gebratener Lachs mit gedämpftem Brokkoli und Zitronen-Kräuterbutter.",
        "image_url": "",
        "total_time_minutes": 25,
        "difficulty": "einfach",
        "rating": 4.7,
        "rating_count": 132,
        "dietary_tags": ["low-carb", "glutenfrei"]
      },
      {
        "type": "recipe",
        "uid": "nr-3-4",
        "title": "Gefüllte Paprika mit Hackfleisch",
        "description": "Bunte Paprika gefüllt mit gewürztem Hackfleisch, Feta und Kräutern.",
        "image_url": "",
        "total_time_minutes": 40,
        "difficulty": "mittel",
        "rating": 4.5,
        "rating_count": 203,
        "dietary_tags": ["low-carb"]
      }
    ]
  }
];

export default examples;
