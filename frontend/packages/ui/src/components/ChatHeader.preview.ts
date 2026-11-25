// figma-visual-proof: not-required. Fixture for the existing web header.
const base = {
  title: 'Private Team message', currentChatId: 'preview-direct-chat',
  category: 'general', icon: 'team', summary: '', chatCreatedAt: 1_760_000_000,
  writable: false, onSaveTitle: async () => {}, onSaveDescription: async () => {},
};

export default base;
export const variants = {
  introPoster: {
    ...base,
    title: 'Explore OpenMates',
    videoTeaserWebpUrl: '/intro-teasers/openmates-intro-teaser.webp',
    videoTeaserMp4Url: '/intro-teasers/openmates-intro-teaser.mp4',
    videoMp4Url: '/intro-teasers/openmates-intro-teaser.mp4',
  },
  teamDirect: { ...base, isDirectChat: true },
  subChat: { ...base, title: 'Check the announcement channel', isSubChat: true },
};
