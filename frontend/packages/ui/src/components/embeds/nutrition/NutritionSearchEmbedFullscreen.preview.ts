/**
 * frontend/packages/ui/src/components/embeds/nutrition/NutritionSearchEmbedFullscreen.preview.ts
 *
 * Mock props for the nutrition search fullscreen view.
 * Access at: /dev/preview/embeds/nutrition/NutritionSearchEmbedFullscreen
 */

import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

const defaultProps = {
  data: {
    embedType: 'app-skill-use',
    appId: 'nutrition',
    skillId: 'search_recipes',
    embedData: { status: 'finished' },
    decodedContent: {
      query: 'vegetarische Pasta',
      provider: 'REWE',
      status: 'finished',
      results: [
        {
          type: 'recipe',
          uid: 'recipe-001',
          title: 'Spaghetti Aglio e Olio',
          description: 'Klassisches italienisches Knoblauch-Pasta-Gericht',
          total_time_minutes: 25,
          difficulty: 'einfach',
          servings: 4,
          rating: 4.7,
          rating_count: 342,
          dietary_tags: ['vegetarisch'],
          ingredients: [
            { amount: '400', unit: 'g', name: 'Spaghetti' },
            { amount: '6', unit: 'Zehen', name: 'Knoblauch' },
            { amount: '100', unit: 'ml', name: 'Olivenöl' },
            { amount: '1', unit: 'TL', name: 'Chiliflocken' }
          ],
          instructions: [
            { step: 1, text: 'Spaghetti in reichlich Salzwasser al dente kochen.' },
            { step: 2, text: 'Knoblauch in dünne Scheiben schneiden.' },
            { step: 3, text: 'Olivenöl in einer Pfanne erhitzen und Knoblauch goldbraun anbraten.' },
            { step: 4, text: 'Chiliflocken hinzugeben, Pasta abgießen und in die Pfanne geben.' }
          ],
          nutrition: { calories_kcal: 520, protein_g: 14, fat_g: 22, carbs_g: 68 }
        },
        {
          type: 'recipe',
          uid: 'recipe-002',
          title: 'Penne Arrabiata',
          description: 'Scharfe Tomatensoße mit Penne',
          total_time_minutes: 30,
          difficulty: 'einfach',
          servings: 4,
          rating: 4.5,
          rating_count: 218,
          dietary_tags: ['vegan']
        }
      ]
    }
  } as unknown as EmbedFullscreenRawData,
  onClose: () => console.log('[Preview] Close clicked'),
  embedId: 'preview-nutrition-search-fs'
};

export default defaultProps;

export const variants = {
  processing: {
    ...defaultProps,
    data: {
      ...defaultProps.data,
      embedData: { status: 'processing' },
      decodedContent: {
        ...defaultProps.data.decodedContent,
        status: 'processing',
        results: []
      }
    } as unknown as EmbedFullscreenRawData
  },
  error: {
    ...defaultProps,
    data: {
      ...defaultProps.data,
      embedData: { status: 'error' },
      decodedContent: {
        ...defaultProps.data.decodedContent,
        status: 'error',
        error: 'REWE recipe API returned an error',
        results: []
      }
    } as unknown as EmbedFullscreenRawData
  }
};
