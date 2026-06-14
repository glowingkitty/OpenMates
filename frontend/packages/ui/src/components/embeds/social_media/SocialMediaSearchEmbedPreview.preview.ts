/**
 * Preview mock data for SocialMediaSearchEmbedPreview.
 * Feeds the web embed showcase and Apple parity contract extraction.
 * Uses synthetic provider-shaped posts to avoid committing private account data
 * or relying on live social media APIs during visual tests.
 */

const posts = [
  {
    platform: 'bluesky',
    page: 'search',
    title: 'Small cafe bar layout notes',
    body: 'A compact espresso bar can still feel calm: warm task lighting, a narrow handoff shelf, and one visible daily special board made this setup feel polished without clutter.',
    author: 'sample.cafe',
    author_display_name: 'Sample Cafe Journal',
    published_at: '2026-05-24T10:30:00Z',
    like_count: 184,
    reply_count: 12,
    repost_count: 27,
    url: 'https://bsky.app/profile/sample.cafe/post/example-1',
  },
  {
    platform: 'bluesky',
    page: 'search',
    title: 'Home pourover station',
    body: 'Keeping grinder, scale, filters and kettle on one tray reduced morning friction more than any equipment upgrade.',
    author: 'dailybrew.example',
    author_display_name: 'Daily Brew Notes',
    published_at: '2026-05-23T18:12:00Z',
    like_count: 96,
    reply_count: 8,
    repost_count: 11,
    url: 'https://bsky.app/profile/dailybrew.example/post/example-2',
  },
  {
    platform: 'bluesky',
    page: 'search',
    title: 'Menu photography tip',
    body: 'Shoot drinks next to the ingredients that define them. Even one citrus peel or spice jar gives people a faster read on flavor.',
    author: 'menu-lab.example',
    author_display_name: 'Menu Lab',
    published_at: '2026-05-22T14:04:00Z',
    like_count: 73,
    reply_count: 5,
    repost_count: 9,
    url: 'https://bsky.app/profile/menu-lab.example/post/example-3',
  },
];

const defaultProps = {
  id: 'preview-social-media-search-1',
  query: 'Indie coffee setup inspiration',
  provider: 'bluesky_public',
  result_count: posts.length,
  results: [{ platform: 'bluesky', page: 'search', posts }],
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => console.log('[Preview] Social media search fullscreen clicked'),
};

export default defaultProps;

export const variants = {
  processing: {
    ...defaultProps,
    id: 'preview-social-media-search-processing',
    result_count: 0,
    results: [],
    status: 'processing' as const,
  },
  error: {
    ...defaultProps,
    id: 'preview-social-media-search-error',
    result_count: 0,
    results: [],
    status: 'error' as const,
  },
  mobile: {
    ...defaultProps,
    id: 'preview-social-media-search-mobile',
    isMobile: true,
  },
};
