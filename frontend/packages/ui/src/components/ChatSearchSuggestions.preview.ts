/** Composer suggestions over public example chats, with no account or server state. */
const defaultProps = {
  messageInputContent: 'Rocket-powered aircraft - Wikipedia',
  currentChatId: 'example-gigantic-airplanes',
  onChatNavigate: (chatId: string) => {
    window.dispatchEvent(new CustomEvent('preview-chat-selected', { detail: chatId }));
  },
  onFileSelect: () => {},
  onEmbedSelect: (embedId: string, _settingsPath?: string, chatId?: string) => {
    window.dispatchEvent(new CustomEvent('preview-embed-selected', { detail: { embedId, chatId } }));
  },
};

export default defaultProps;

export const variants = {
  codeResult: { ...defaultProps, messageInputContent: 'src/main.js' },
};
