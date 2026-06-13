/**
 * App-store examples for the nutrition search_recipes skill.
 *
 * Edamam-shaped sample fixtures. They intentionally avoid live signed image
 * URLs so app-store examples stay stable while still exercising source links,
 * ingredients, instructions, and nutrition sections. A "Sample data" banner is
 * shown at the top of the fullscreen via the is_store_example flag set by
 * SkillExamplesSection.
 */

export interface NutritionSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const quickSpinachPasta = {
  "type": "recipe",
  "uid": "edamam-quick-spinach-pasta",
  "title": "Quick Spinach Pasta",
  "description": "A fast vegetarian pasta with spinach, lemon, garlic, and a light parmesan finish.",
  "source": "Sample source",
  "recipe_url": "https://www.edamam.com/results/recipes/?search=quick%20spinach%20pasta",
  "image_url": null,
  "total_time_minutes": 25,
  "servings": 4,
  "dietary_tags": ["Vegetarian"],
  "health_labels": ["Vegetarian", "Peanut-Free", "Tree-Nut-Free"],
  "diet_labels": ["Balanced"],
  "cuisine_type": ["italian"],
  "meal_type": ["lunch/dinner"],
  "dish_type": ["main course"],
  "ingredients": [
    { "amount": "350", "unit": "g", "name": "pasta" },
    { "amount": "3", "unit": "tbsp", "name": "olive oil" },
    { "amount": "3", "unit": "", "name": "garlic cloves" },
    { "amount": "200", "unit": "g", "name": "baby spinach" },
    { "amount": "1", "unit": "", "name": "lemon" },
    { "amount": "40", "unit": "g", "name": "parmesan" }
  ],
  "instructions": [
    { "step": 1, "text": "Cook the pasta in salted water until al dente, reserving a small cup of pasta water." },
    { "step": 2, "text": "Warm olive oil in a large pan and saute the sliced garlic until fragrant." },
    { "step": 3, "text": "Add spinach and cook until just wilted, then fold in the drained pasta." },
    { "step": 4, "text": "Add lemon zest, lemon juice, parmesan, and enough pasta water to coat the noodles." }
  ],
  "nutrition": {
    "calories_kcal": 520,
    "protein_g": 17,
    "fat_g": 18,
    "carbs_g": 72
  },
  "provider": "Edamam"
};

const sweetPotatoChickpeaBowl = {
  "type": "recipe",
  "uid": "edamam-sweet-potato-chickpea-bowl",
  "title": "Sweet Potato Chickpea Bowl",
  "description": "A simple plant-based dinner bowl with roasted sweet potato, chickpeas, greens, and tahini dressing.",
  "source": "Sample source",
  "recipe_url": "https://www.edamam.com/results/recipes/?search=sweet%20potato%20chickpea%20bowl",
  "image_url": null,
  "total_time_minutes": 40,
  "servings": 2,
  "dietary_tags": ["Vegan", "High-Fiber"],
  "health_labels": ["Vegan", "Vegetarian", "Dairy-Free"],
  "diet_labels": ["High-Fiber"],
  "cuisine_type": ["american"],
  "meal_type": ["lunch/dinner"],
  "dish_type": ["main course"],
  "ingredients": [
    { "amount": "2", "unit": "", "name": "sweet potatoes" },
    { "amount": "1", "unit": "can", "name": "chickpeas" },
    { "amount": "2", "unit": "tbsp", "name": "olive oil" },
    { "amount": "1", "unit": "tsp", "name": "smoked paprika" },
    { "amount": "3", "unit": "cups", "name": "mixed greens" },
    { "amount": "2", "unit": "tbsp", "name": "tahini" }
  ],
  "instructions": [
    { "step": 1, "text": "Heat the oven to 220 C and line a baking tray." },
    { "step": 2, "text": "Toss sweet potato cubes and chickpeas with olive oil, paprika, salt, and pepper." },
    { "step": 3, "text": "Roast until the sweet potato is tender and the chickpeas are crisp at the edges." },
    { "step": 4, "text": "Whisk tahini with lemon juice and water, then serve everything over greens." }
  ],
  "nutrition": {
    "calories_kcal": 610,
    "protein_g": 19,
    "fat_g": 24,
    "carbs_g": 82
  },
  "provider": "Edamam"
};

const misoSalmonCucumberRice = {
  "type": "recipe",
  "uid": "edamam-miso-salmon-cucumber-rice",
  "title": "Miso Salmon with Cucumber Rice",
  "description": "A protein-rich salmon dinner with a quick miso glaze, cucumber rice, and sesame.",
  "source": "Sample source",
  "recipe_url": "https://www.edamam.com/results/recipes/?search=miso%20salmon%20cucumber%20rice",
  "image_url": null,
  "total_time_minutes": 30,
  "servings": 2,
  "dietary_tags": ["High-Protein"],
  "health_labels": ["Dairy-Free", "Peanut-Free"],
  "diet_labels": ["High-Protein", "Low-Carb"],
  "cuisine_type": ["japanese"],
  "meal_type": ["lunch/dinner"],
  "dish_type": ["main course"],
  "ingredients": [
    { "amount": "2", "unit": "", "name": "salmon fillets" },
    { "amount": "1", "unit": "tbsp", "name": "white miso" },
    { "amount": "1", "unit": "tbsp", "name": "soy sauce" },
    { "amount": "1", "unit": "tsp", "name": "honey" },
    { "amount": "1", "unit": "", "name": "cucumber" },
    { "amount": "2", "unit": "cups", "name": "cooked rice" }
  ],
  "instructions": [
    { "step": 1, "text": "Whisk miso, soy sauce, honey, and a splash of water into a smooth glaze." },
    { "step": 2, "text": "Brush the salmon with the glaze and bake or pan-sear until just cooked through." },
    { "step": 3, "text": "Fold diced cucumber and sesame into warm rice." },
    { "step": 4, "text": "Serve the salmon over the cucumber rice with any remaining glaze spooned on top." }
  ],
  "nutrition": {
    "calories_kcal": 640,
    "protein_g": 42,
    "fat_g": 24,
    "carbs_g": 58
  },
  "provider": "Edamam"
};

const examples: NutritionSearchStoreExample[] = [
  {
    "id": "store-example-nutrition-search-recipes-1",
    "query": "Vegetarische Pasta",
    "query_translation_key": "settings.app_store_examples.nutrition.search_recipes.1",
    "provider": "Sample Data",
    "status": "finished",
    "results": [quickSpinachPasta, sweetPotatoChickpeaBowl, misoSalmonCucumberRice]
  },
  {
    "id": "store-example-nutrition-search-recipes-2",
    "query": "Einfache Abendessen",
    "query_translation_key": "settings.app_store_examples.nutrition.search_recipes.2",
    "provider": "Sample Data",
    "status": "finished",
    "results": [sweetPotatoChickpeaBowl, quickSpinachPasta, misoSalmonCucumberRice]
  },
  {
    "id": "store-example-nutrition-search-recipes-3",
    "query": "Low Carb Abendessen",
    "query_translation_key": "settings.app_store_examples.nutrition.search_recipes.3",
    "provider": "Sample Data",
    "status": "finished",
    "results": [misoSalmonCucumberRice, sweetPotatoChickpeaBowl, quickSpinachPasta]
  }
];

export default examples;
