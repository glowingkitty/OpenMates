---
status: active
doc_type: guide
audience:
  - end-users
last_verified: 2026-06-11
claims:
  - id: user-guide-apps-nutrition-source
    type: unit
    claim: The Nutrition app guide is grounded in the Nutrition app metadata.
    file: scripts/tests/test_user_guide_app_docs_claims.py
    assertion: user-guide-apps-nutrition-source
---

# Nutrition

> Search recipes by natural-language query, dietary needs, ingredients, and meal type.

## What It Does

The Nutrition app finds recipes from Edamam's web recipe search and returns full details including ingredients, step-by-step instructions, images, source links, nutrition info, and dietary labels. Recipes without instructions are filtered out before results are shown.

**Available skills:**

- **Search Recipes** -- Search Edamam recipes by natural-language query and optional nutrition filters. Returns full recipe details: ingredients, step-by-step instructions, image data, source links, nutrition info, and dietary labels.

**Supported filters:**

- **Query** -- free-text recipe search such as "quick vegan pasta", "gluten-free pancakes", or "miso salmon"
- **Diet** -- balanced, high-fiber, high-protein, low-carb, low-fat, low-sodium
- **Health** -- vegan, vegetarian, gluten-free, dairy-free, keto-friendly, peanut-free, tree-nut-free, and more
- **Time** -- ranges such as `1-30` for quicker recipes
- **Meal and dish type** -- breakfast, dinner, lunch, snack, soup, salad, main course, pancake, and more
- **Exclusions** -- ingredients or terms to avoid

## How to Use It

- Find a quick weeknight dinner: "Show me easy vegetarian pasta recipes"
- Filter by diet: "Find vegan gluten-free desserts"
- Plan a meal: "Suggest a low-carb main course with chicken"
- Browse by occasion: "Recipes for a kids birthday party"

## Tips

- Recipes are sourced from Edamam's web recipe index and include source links for attribution.
- Combine a natural-language query with filters to narrow results (e.g. `vegan` + `gluten-free` + `1-30`).
- Each recipe card shows ingredients, instructions, prep time when available, servings, nutrition, and dietary labels. Click to see the full recipe in fullscreen.
- Saved recipes and meal plans are stored in your Nutrition memories so your mate can refer back to them later.

## Related

- [Shopping](./shopping.md) -- Search groceries and products
- [Health](./health.md) -- Track dietary preferences and medical history
