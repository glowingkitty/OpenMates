/**
 * Offline media for the embroidery component previews and store examples.
 * A flat fox graphic (the prepared SVG) and a stitch-like rendering of it
 * (the stitch preview), both 90 x 74 mm in aspect ratio.
 */

export const FOX_PREPARED_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 296" width="360" height="296"><path d="M180 40 L250 110 L300 90 L290 190 L240 255 L180 270 L120 255 L70 190 L60 90 L110 110 Z" fill="#e8742c"/><path d="M180 150 L225 205 L180 232 L135 205 Z" fill="#fbf4ea"/><circle cx="145" cy="130" r="12" fill="#2b2d42"/><circle cx="215" cy="130" r="12" fill="#2b2d42"/></svg>';

export const FOX_STITCH_PREVIEW_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 296" width="360" height="296"><defs><pattern id="a" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><rect width="5" height="5" fill="#e8742c"/><rect width="5" height="1.6" fill="#b9561a"/></pattern><pattern id="b" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(-20)"><rect width="4" height="4" fill="#fbf4ea"/><rect width="4" height="1.3" fill="#d9cdb9"/></pattern><pattern id="c" width="3" height="3" patternUnits="userSpaceOnUse"><rect width="3" height="3" fill="#2b2d42"/><rect width="3" height="1" fill="#14151f"/></pattern></defs><rect width="360" height="296" fill="#f4f1ea"/><path d="M180 40 L250 110 L300 90 L290 190 L240 255 L180 270 L120 255 L70 190 L60 90 L110 110 Z" fill="url(#a)" stroke="#8c3f0e" stroke-width="2"/><path d="M180 150 L225 205 L180 232 L135 205 Z" fill="url(#b)" stroke="#b8ab94" stroke-width="2"/><circle cx="145" cy="130" r="12" fill="url(#c)"/><circle cx="215" cy="130" r="12" fill="url(#c)"/></svg>';

export const FOX_STITCH_PREVIEW_URL = `data:image/svg+xml,${encodeURIComponent(FOX_STITCH_PREVIEW_SVG)}`;

/** Finished fox result as the backend delivers it, minus encrypted file descriptors. */
export const FOX_RESULT = {
  app_id: 'design',
  skill_id: 'embroidery',
  type: 'embroidery_design',
  status: 'finished',
  title: 'Fox',
  width_mm: 90,
  height_mm: 74,
  stitch_count: 12840,
  thread_changes: 3,
  estimated_minutes: 29,
  thread_length_m: 41.6,
  hoop: '130x180',
  fits_hoop: 'yes',
  fabric: 'normal',
  reworked: false,
  threads: [
    { colour_hex: '#e8742c', name: 'Madeira 1135', stitch_count: 8120, estimated_minutes: 17, thread_length_m: 26.4 },
    { colour_hex: '#ffffff', name: 'Madeira 1001', stitch_count: 3410, estimated_minutes: 8, thread_length_m: 11 },
    { colour_hex: '#2b2d42', name: 'Madeira 1005', stitch_count: 1310, estimated_minutes: 3, thread_length_m: 4.2 },
  ],
  notes: [{ code: 'background_removed', text: 'Background left out' }],
  previewImageUrl: FOX_STITCH_PREVIEW_URL,
  preparedSvgText: FOX_PREPARED_SVG,
  previewDownloadText: '#EMBROIDERY component preview file',
};
