/**
 * Preview mock data for SocialMediaGetPostsEmbedPreview.
 * Feeds the web embed showcase and Apple parity contract extraction.
 * Uses synthetic provider-shaped posts to avoid promoting real accounts or
 * committing private social media content in visual fixtures.
 */

const posts = [
  {
    platform: 'bluesky',
    page: '@samplegarden.example',
    title: 'Balcony herbs after rain',
    body: 'Mint and basil bounced back fastest after moving the planters closer to the wall. The wind break mattered more than the fertilizer schedule.',
    author: 'samplegarden.example',
    author_display_name: 'Sample Garden Log',
    published_at: '2026-05-24T08:05:00Z',
    like_count: 129,
    reply_count: 14,
    repost_count: 18,
    url: 'https://bsky.app/profile/samplegarden.example/post/example-1',
  },
  {
    platform: 'bluesky',
    page: '@samplegarden.example',
    title: 'Compost reminder',
    body: 'The easiest rule I have found: if the bin smells sharp, add dry browns; if nothing changes for a week, add greens and turn once.',
    author: 'samplegarden.example',
    author_display_name: 'Sample Garden Log',
    published_at: '2026-05-22T11:36:00Z',
    like_count: 88,
    reply_count: 7,
    repost_count: 10,
    url: 'https://bsky.app/profile/samplegarden.example/post/example-2',
  },
  {
    platform: 'bluesky',
    page: '@samplegarden.example',
    title: 'Seedling notes',
    body: 'Labeling trays with both variety and sowing date made thinning decisions much easier two weeks later.',
    author: 'samplegarden.example',
    author_display_name: 'Sample Garden Log',
    published_at: '2026-05-19T15:10:00Z',
    like_count: 64,
    reply_count: 3,
    repost_count: 6,
    url: 'https://bsky.app/profile/samplegarden.example/post/example-3',
  },
];

const defaultProps = {
  id: 'preview-social-media-get-posts-1',
  query: '@samplegarden.example',
  provider: 'bluesky_public',
  result_count: posts.length,
  results: [{ platform: 'bluesky', page: '@samplegarden.example', posts }],
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => console.log('[Preview] Social media get posts fullscreen clicked'),
};

export default defaultProps;

export const variants = {
  processing: {
    ...defaultProps,
    id: 'preview-social-media-get-posts-processing',
    result_count: 0,
    results: [],
    status: 'processing' as const,
  },
  error: {
    ...defaultProps,
    id: 'preview-social-media-get-posts-error',
    result_count: 0,
    results: [],
    status: 'error' as const,
  },
  mobile: {
    ...defaultProps,
    id: 'preview-social-media-get-posts-mobile',
    isMobile: true,
  },
};
