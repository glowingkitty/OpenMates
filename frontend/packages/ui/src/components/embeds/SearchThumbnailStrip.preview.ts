/**
 * Isolated preview for the shared search thumbnail strip.
 * Uses bundled images so the fixture needs no provider request.
 * Parent search components own normalization and bounded selection.
 * Open /dev/preview/embeds/SearchThumbnailStrip?chrome=0.
 * Architecture: docs/architecture/embeds.md
 */
export default {
  appId: 'web',
  images: [
    { url: '/images/examples/group1.jpg', title: 'First search result' },
    { url: '/images/examples/group2.jpg', title: 'Second search result' },
  ],
};
