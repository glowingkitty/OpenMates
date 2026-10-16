/**
 * frontend/packages/ui/src/components/embeds/nutrition/NutritionRecipeEmbedFullscreen.preview.ts
 *
 * Mock props for the single recipe fullscreen detail view.
 * Access at: /dev/preview/embeds/nutrition/NutritionRecipeEmbedFullscreen
 */

const sampleRecipe = {
  embed_id: 'preview-recipe-fs-001',
  title: 'Spaghetti Aglio e Olio',
  description: 'Klassisches italienisches Knoblauch-Pasta-Gericht mit Olivenöl, Knoblauch und Chili. Einfach, schnell und unglaublich lecker.',
  image_url: null,
  recipe_url: 'https://www.edamam.com/results/recipes/?search=spaghetti%20aglio%20e%20olio',
  prep_time_minutes: 10,
  cook_time_minutes: 15,
  total_time_minutes: 25,
  difficulty: 'einfach',
  servings: 4,
  rating: 4.7,
  rating_count: 342,
  ernaehrwert_score: 6,
  dietary_tags: ['vegetarisch'],
  categories: ['Hauptspeise', 'Pasta', 'Italienisch'],
  ingredients: [
    { amount: '400', unit: 'g', name: 'Spaghetti' },
    { amount: '6', unit: 'Zehen', name: 'Knoblauch' },
    { amount: '100', unit: 'ml', name: 'Olivenöl (extra vergine)' },
    { amount: '1', unit: 'TL', name: 'Chiliflocken' },
    { amount: '1', unit: 'Bund', name: 'Petersilie' },
    { name: 'Salz und Pfeffer' }
  ],
  instructions: [
    { step: 1, text: 'Spaghetti in einem großen Topf mit reichlich Salzwasser al dente kochen. Etwas Kochwasser aufheben.' },
    { step: 2, text: 'Knoblauch schälen und in dünne Scheiben schneiden. Petersilie fein hacken.' },
    { step: 3, text: 'Olivenöl in einer großen Pfanne bei mittlerer Hitze erwärmen. Knoblauch darin goldbraun anbraten (nicht zu dunkel!).' },
    { step: 4, text: 'Chiliflocken zum Knoblauch geben und kurz mitrösten.' },
    { step: 5, text: 'Abgetropfte Spaghetti in die Pfanne geben, mit etwas Kochwasser vermengen. Mit Petersilie, Salz und Pfeffer abschmecken.' }
  ],
  nutrition: {
    calories_kcal: 520,
    protein_g: 14,
    fat_g: 22,
    carbs_g: 68
  }
};

const defaultProps = {
  recipe: sampleRecipe,
  embedId: 'preview-recipe-fs-001',
  onClose: () => console.log('[Preview] Close clicked')
};

export default defaultProps;

export const variants = {
  /** The raw envelope supplied by ActiveChat for a saved inline recipe child. */
  directData: {
    recipe: undefined, // Preview variants merge with default props; remove the legacy input.
    data: {
      decodedContent: {
        type: 'recipe',
        app_id: 'nutrition',
        skill_id: 'search_recipes',
        title: 'Slow cooker chickpeas and spinach stew',
        servings: 4,
        total_time_minutes: 795,
        calories_per_serving: 390.32275000000004,
        ingredients: [
          { text: '350 g of dry chickpeas, soaked in water for 12 hours', quantity: 350, measure: 'gram', food: 'chickpeas' },
          { text: '½ red bell pepper', quantity: 0.5, measure: '<unit>', food: 'red bell pepper' },
          { text: '200 g spinach or swiss chard', quantity: 200, measure: 'gram', food: 'swiss chard' }
        ],
        instructions: [{ step: 1, text: 'Heat the oil in a small pan over high heat.' }],
        diet_labels: 'High-Fiber',
        health_labels: 'Vegan|Vegetarian',
        cuisine_type: 'american',
        nutrition_PROCNT_quantity: 81.44995,
        nutrition_PROCNT_unit: 'g',
        nutrition_FAT_quantity: 28.041700000000002,
        nutrition_FAT_unit: 'g',
        nutrition_CHOCDF_quantity: 263.09475,
        nutrition_CHOCDF_unit: 'g'
      }
    },
    embedId: '9c8b68fa-8220-4a7c-be8a-e18350135861',
    onClose: () => {}
  },
  /** Recipe with extensive data */
  fullData: {
    recipe: {
      ...sampleRecipe,
      embed_id: 'preview-recipe-fs-full',
      title: 'Vegane Gemüse-Lasagne',
      difficulty: 'mittel',
      total_time_minutes: 75,
      servings: 6,
      rating: 4.8,
      rating_count: 89,
      ernaehrwert_score: 9,
      dietary_tags: ['vegan', 'glutenfrei', 'laktosefrei'],
      categories: ['Hauptspeise', 'Auflauf']
    },
    embedId: 'preview-recipe-fs-full',
    onClose: () => {}
  },

  /** Minimal recipe data */
  minimal: {
    recipe: {
      embed_id: 'preview-recipe-fs-minimal',
      title: 'Einfacher Gurkensalat'
    },
    embedId: 'preview-recipe-fs-minimal',
    onClose: () => {}
  }
};
