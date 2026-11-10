/**
 * Preview fixtures for DesignEmbroideryEmbedFullscreen.
 * Access at: /dev/preview/embeds/design/DesignEmbroideryEmbedFullscreen?chrome=0&variant=finished
 */
import { FOX_RESULT } from './embroideryFixtures';

const EMBED_ID = '5d1f0c52-8f3e-4d8a-9a52-3d2f7b9a41e6';

function fixture(content: Record<string, unknown>, status = 'finished') {
  return {
    embedId: EMBED_ID,
    data: { decodedContent: content, embedData: { status } },
    onClose: () => {},
  };
}

const defaultProps = fixture(FOX_RESULT);

export default defaultProps;

export const variants = {
  finished: defaultProps,
  processing: fixture({ app_id: 'design', skill_id: 'embroidery', title: 'Fox' }, 'processing'),
  error: fixture({
    app_id: 'design', skill_id: 'embroidery', status: 'error', title: 'Fox',
    error: 'too many stitches', error_code: 'too_many_stitches',
  }, 'error'),
  nothingToSew: fixture({
    app_id: 'design', skill_id: 'embroidery', status: 'error', title: 'Fox',
    error: 'Nothing to sew after leaving out the background', error_code: 'nothing_to_sew',
  }, 'error'),
  reworked: fixture({
    ...FOX_RESULT, reworked: true, fabric: 'stretchy',
    notes: [
      { code: 'background_removed', text: 'Background left out' },
      { code: 'tiny_details_removed', text: '3 detail(s) too small to sew left out', count: 3 },
      { code: 'solved_gradient_or_filter', text: 'Gradients and filters replaced by flat colours' },
      { code: 'a_future_note', text: 'The tail was drawn a little wider' },
    ],
  }),
  hoopTooSmall: fixture({ ...FOX_RESULT, width_mm: 150, height_mm: 124, hoop: '100x100', fits_hoop: 'no' }),
  hoopNotChecked: fixture({ ...FOX_RESULT, hoop: 'none', fits_hoop: 'not_checked' }),
  downloadUnavailable: fixture({ ...FOX_RESULT, previewDownloadText: '' }),
  withBorder: fixture({
    ...FOX_RESULT, border_mm: 3,
    threads: [{ colour_hex: '#000000', name: 'Madeira 1000', stitch_count: 2400 }, ...FOX_RESULT.threads],
    thread_changes: 4,
    notes: [...FOX_RESULT.notes, { code: 'border_added', mm: 3, text: 'Border of 3 mm added for sewing on' }],
  }),
  noNotes: fixture({ ...FOX_RESULT, notes: [] }),
};
