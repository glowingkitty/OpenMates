/** New-chat composer suggestions over public examples, without account state. */
const defaultProps = {
  messageInputContent: 'Berlin',
  onSuggestionClick: () => {},
  onChatNavigate: () => {},
  onFileSelect: () => {},
  onEmbedSelect: (embedId: string) => {
    window.dispatchEvent(new CustomEvent('preview-embed-selected', { detail: embedId }));
  },
};

export default defaultProps;
