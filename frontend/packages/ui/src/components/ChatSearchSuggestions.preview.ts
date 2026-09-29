/** Composer suggestions over public example chats, with no account or server state. */
const defaultProps = {
  messageInputContent: 'Berlin',
  currentChatId: 'example-ai-workshops-meetups-berlin',
  onChatNavigate: (chatId: string) => {
    window.dispatchEvent(new CustomEvent('preview-chat-selected', { detail: chatId }));
  },
  onFileSelect: () => {},
  onEmbedSelect: (embedId: string) => {
    window.dispatchEvent(new CustomEvent('preview-embed-selected', { detail: embedId }));
  },
};

export default defaultProps;
