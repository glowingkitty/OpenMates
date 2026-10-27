const post = {
 title: 'Community cafe research notes', body: 'A quiet reading corner and accessible handoff shelf make shared spaces useful.',
 author: 'sample.cafe', author_display_name: 'Sample Cafe Journal', platform: 'bluesky', page: 'search',
 url: 'https://bsky.app/profile/sample.cafe/post/example-1', published_at: '2026-05-24T10:30:00Z',
 like_count: 184, reply_count: 12, repost_count: 27,
 media_url: 'https://images.example.com/cafe.jpg',
 external_url: 'https://example.com/cafe-research', external_title: 'Read the research notes',
 comments: [{ author: 'reader', body: 'The accessible shelf makes this much easier to use.', score: 5 }],
};
const defaultProps = { embedId: 'preview-social-post', data: { decodedContent: post }, onClose: () => {} };
export default defaultProps;
export const variants = {
 missingData: { ...defaultProps, data: { decodedContent: { title: 'Social post', body: 'A saved post without engagement metadata.' } } },
 longPost: { ...defaultProps, data: { decodedContent: { ...post, body: 'Accessible community spaces support quiet reading, research and conversation. '.repeat(30) } } },
};
