/**
 * frontend/packages/ui/src/components/embeds/nutrition/NutritionSearchEmbedPreview.preview.ts
 *
 * Preview mock data for NutritionSearchEmbedPreview (nutrition/search_recipes skill result).
 * Access at: /dev/preview/embeds/nutrition/NutritionSearchEmbedPreview
 */

const sampleResults = [
  {
    uid: 'rewe-recipe-001',
    title: 'Spaghetti Aglio e Olio',
    description: 'Klassisches italienisches Knoblauch-Pasta-Gericht',
    image_url: null,
    total_time_minutes: 25,
    difficulty: 'einfach',
    rating: 4.7,
    rating_count: 342,
    dietary_tags: ['vegetarisch'],
    servings: 4
  },
  {
    uid: 'rewe-recipe-002',
    title: 'Penne Arrabiata mit frischen Tomaten',
    description: 'Scharfe Tomatensoße mit Penne',
    image_url: null,
    total_time_minutes: 30,
    difficulty: 'einfach',
    rating: 4.5,
    rating_count: 218,
    dietary_tags: ['vegan'],
    servings: 4
  },
  {
    uid: 'rewe-recipe-003',
    title: 'Tagliatelle mit Pilzrahmsauce',
    description: 'Cremige Pilzsauce mit frischen Kräutern',
    image_url: null,
    total_time_minutes: 35,
    difficulty: 'mittel',
    rating: 4.8,
    rating_count: 156,
    dietary_tags: ['vegetarisch'],
    servings: 2
  }
];

/** Default props — shows a finished recipe search with results */
const defaultProps = {
  id: 'preview-nutrition-search-1',
  query: 'vegetarische Pasta',
  provider: 'REWE',
  status: 'finished' as const,
  results: sampleResults,
  isMobile: false,
  onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Processing state — searching */
  processing: {
    id: 'preview-nutrition-search-processing',
    query: 'schnelle Abendessen Rezepte',
    provider: 'REWE',
    status: 'processing' as const,
    results: [],
    isMobile: false,
    onFullscreen: () => {}
  },

  /** Error state */
  error: {
    id: 'preview-nutrition-search-error',
    query: 'vegane Kuchen',
    provider: 'REWE',
    status: 'error' as const,
    results: [],
    isMobile: false,
    onFullscreen: () => {}
  },

  /** Cancelled state */
  cancelled: {
    id: 'preview-nutrition-search-cancelled',
    query: 'low carb Rezepte',
    provider: 'REWE',
    status: 'cancelled' as const,
    results: [],
    isMobile: false,
    onFullscreen: () => {}
  },

  /** Mobile view */
  mobile: {
    ...defaultProps,
    id: 'preview-nutrition-search-mobile',
    isMobile: true
  }
};
