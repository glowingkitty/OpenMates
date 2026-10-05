import type { WikipediaArticleIdentity, WikipediaRelatedArticle } from '../../../utils/wikipediaLearning';

function record(action: string, value?: unknown) {
  document.dispatchEvent(new CustomEvent('preview-wiki-action', { detail: { action, value } }));
}

const defaultProps = {
  wikiTitle: 'Ada_Lovelace', displayText: 'Ada Lovelace', language: 'en',
  isAuthenticated: true, hasChatContext: true,
  onClose: () => record('close'),
  onSendQuestion: async (question: string, article: WikipediaArticleIdentity) => { record('send', { question, article }); return true; },
  onSaveInterest: async (article: WikipediaArticleIdentity) => { record('save', article); return 'preview-study-goal'; },
  onFindInterest: () => null,
  onOpenInterest: (id: string) => record('edit', id),
  onRelatedArticle: (article: WikipediaRelatedArticle) => record('related', article),
  onAuthenticate: () => record('login'),
};

export default defaultProps;
export const variants = {
  signedOut: { ...defaultProps, isAuthenticated: false },
  noChat: { ...defaultProps, hasChatContext: false },
  saved: { ...defaultProps, onFindInterest: () => 'existing-study-goal' },
  failedSend: { ...defaultProps, onSendQuestion: async () => false },
  pendingSend: { ...defaultProps, onSendQuestion: async (question: string) => {
    record('send', question);
    await new Promise<void>(resolve => document.addEventListener('preview-wiki-resolve-send', () => resolve(), { once: true }));
    return true;
  } },
};
