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
  recipe_url: 'https://www.rewe.de/rezepte/spaghetti-aglio-olio/',
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
