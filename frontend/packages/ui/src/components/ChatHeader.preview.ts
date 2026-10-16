const base = {
  title: 'Private Team message', currentChatId: 'preview-direct-chat',
  category: 'general', icon: 'team', summary: '', chatCreatedAt: 1_760_000_000,
  writable: false, onSaveTitle: async () => {}, onSaveDescription: async () => {},
};

export default base;
export const variants = {
  teamDirect: { ...base, isDirectChat: true },
};
