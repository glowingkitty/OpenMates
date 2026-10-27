/** New-chat composer suggestions over public examples, without account state. */
const defaultProps = {
  messageInputContent: 'Rocket-powered aircraft - Wikipedia',
  onSuggestionClick: () => {},
  onChatNavigate: () => {},
  onFileSelect: () => {},
  onEmbedSelect: (embedId: string, _settingsPath?: string, chatId?: string) => {
    window.dispatchEvent(new CustomEvent('preview-embed-selected', { detail: { embedId, chatId } }));
  },
};

export default defaultProps;

export const variants = {
  codeResult: { ...defaultProps, messageInputContent: 'src/main.js' },
};
