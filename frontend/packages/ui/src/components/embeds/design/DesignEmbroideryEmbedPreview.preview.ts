/**
 * Preview fixtures for DesignEmbroideryEmbedPreview.
 * Media is inline (no network): previewImageUrl stands in for the decrypted stitch preview.
 * Access at: /dev/preview/embeds/design/DesignEmbroideryEmbedPreview
 */
import { FOX_RESULT } from './embroideryFixtures';

const defaultProps = {
  id: 'preview-design-embroidery',
  content: FOX_RESULT as Record<string, unknown>,
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  finished: defaultProps,
  processing: {
    ...defaultProps,
    id: 'preview-design-embroidery-processing',
    content: { app_id: 'design', skill_id: 'embroidery', status: 'processing', title: 'Fox' } as Record<string, unknown>,
    status: 'processing' as const,
  },
  error: {
    ...defaultProps,
    id: 'preview-design-embroidery-error',
    content: {
      app_id: 'design', skill_id: 'embroidery', status: 'error', title: 'Fox',
      error: 'too many stitches', error_code: 'too_many_stitches',
    } as Record<string, unknown>,
    status: 'error' as const,
  },
  withNotes: {
    ...defaultProps,
    id: 'preview-design-embroidery-notes',
    content: {
      ...FOX_RESULT, reworked: true,
      notes: [
        { code: 'background_removed', text: 'Background left out' },
        { code: 'solved_more_than_12_colours', text: 'Colours reduced to at most 12 threads' },
      ],
    } as Record<string, unknown>,
  },
  manyThreads: {
    ...defaultProps,
    id: 'preview-design-embroidery-many-threads',
    content: {
      ...FOX_RESULT, title: 'A very long design name that needs to be cut off at two lines on the card',
      thread_changes: 11,
      threads: Array.from({ length: 12 }, (_, index) => ({
        colour_hex: ['#d7263d', '#f46036', '#e8c547', '#2e86ab', '#ffffff', '#101010'][index % 6],
        name: `Thread ${index + 1}`, stitch_count: 900 + index * 40,
      })),
    } as Record<string, unknown>,
  },
};
