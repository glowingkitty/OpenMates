/**
 * Preview mock data for SocialMediaPostEmbedPreview.
 * Feeds the web embed showcase and Apple parity contract extraction.
 * The post is synthetic and provider-shaped so visual fixtures stay public and
 * deterministic across local, CI, and native parity runs.
 */

const defaultProps = {
  presentationOnly: true,
  id: 'preview-social-media-post-1',
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
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => console.log('[Preview] Social media post fullscreen clicked'),
};

export default defaultProps;

export const variants = {
  invalidDate: { ...defaultProps, published_at: 'not-a-publication-date' },
  missingData: { ...defaultProps, published_at: undefined, like_count: undefined, reply_count: undefined, repost_count: undefined, author_avatar_url: undefined, media_url: undefined },
  longTitle: { ...defaultProps, title: 'Community research notes for an accessible and sustainable neighbourhood cafe and library' },
  chat: { ...defaultProps, resultContext: 'chat' as const },
  textOnly: {
    ...defaultProps,
    id: 'preview-social-media-post-text-only',
    media_url: undefined,
    thumbnail_url: undefined,
  },
  mobile: {
    ...defaultProps,
    id: 'preview-social-media-post-mobile',
    isMobile: true,
  },
};
