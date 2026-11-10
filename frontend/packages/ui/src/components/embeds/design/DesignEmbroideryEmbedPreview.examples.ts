/**
 * App-store examples for the design/embroidery skill.
 *
 * Two realistic finished conversions. The media is inline (see embroideryFixtures.ts),
 * so the cards render without the network and without the encrypted S3 pipeline;
 * the preview component reads `previewImageUrl` and `preparedSvgText` directly.
 */
import { FOX_RESULT } from './embroideryFixtures';

export interface DesignEmbroideryStoreExample extends Record<string, unknown> {
  id: string;
  query: string;
  query_translation_key: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: DesignEmbroideryStoreExample[] = [
  {
    ...FOX_RESULT,
    id: 'store-example-design-embroidery-1',
    query: 'Fox logo for a cap, 90 mm',
    query_translation_key: 'settings.app_store_examples.design.embroidery.1',
    status: 'finished',
    results: [],
  },
  {
    ...FOX_RESULT,
    id: 'store-example-design-embroidery-2',
    query: 'Fox patch on stretchy fabric, 60 mm',
    query_translation_key: 'settings.app_store_examples.design.embroidery.2',
    title: 'Fox patch',
    width_mm: 60,
    height_mm: 49,
    stitch_count: 6120,
    estimated_minutes: 24,
    hoop: '100x100',
    fits_hoop: 'yes',
    fabric: 'stretchy',
    threads: [
      { colour_hex: '#e8742c', name: 'Madeira 1135', stitch_count: 3980 },
      { colour_hex: '#ffffff', name: 'Madeira 1001', stitch_count: 1530 },
      { colour_hex: '#2b2d42', name: 'Madeira 1005', stitch_count: 610 },
    ],
    notes: [
      { code: 'background_removed', text: 'Background left out' },
      { code: 'tiny_details_removed', text: '4 detail(s) too small to sew left out', count: 4 },
    ],
    status: 'finished',
    results: [],
  },
];

export default examples;
