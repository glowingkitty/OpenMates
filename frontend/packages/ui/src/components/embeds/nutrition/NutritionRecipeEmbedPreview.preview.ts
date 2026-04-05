/**
 * frontend/packages/ui/src/components/embeds/nutrition/NutritionRecipeEmbedPreview.preview.ts
 *
 * Mock props for a single recipe card shown inside search grids and as standalone embeds.
 * Access at: /dev/preview/embeds/nutrition/NutritionRecipeEmbedPreview
 */

const defaultProps = {
  id: 'preview-nutrition-recipe-1',
  title: 'Spaghetti Aglio e Olio',
  description: 'Klassisches italienisches Knoblauch-Pasta-Gericht mit Olivenöl und Chili',
  image_url: null,
  total_time_minutes: 25,
  difficulty: 'einfach',
  rating: 4.7,
  rating_count: 342,
  dietary_tags: ['vegetarisch'],
  servings: 4,
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

export const variants = {
  /** Recipe with many tags */
  multiTag: {
    ...defaultProps,
    id: 'preview-nutrition-recipe-multi-tag',
    title: 'Vegane Gemüse-Lasagne ohne Gluten',
    dietary_tags: ['vegan', 'glutenfrei', 'laktosefrei'],
    difficulty: 'mittel',
    total_time_minutes: 60,
    rating: 4.3,
    rating_count: 89
  },

  /** Difficult recipe with long cook time */
  hardRecipe: {
    ...defaultProps,
    id: 'preview-nutrition-recipe-hard',
    title: 'Beef Wellington mit Trüffel-Duxelles',
    difficulty: 'schwer',
    total_time_minutes: 180,
    rating: 4.9,
    rating_count: 56,
    dietary_tags: [],
    servings: 6
  },

  /** No rating or time */
  minimal: {
    id: 'preview-nutrition-recipe-minimal',
    title: 'Einfacher Gurkensalat',
    status: 'finished' as const,
    isMobile: false,
    onFullscreen: () => {}
  },

  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: 'preview-nutrition-recipe-mobile',
    isMobile: true
  }
};
