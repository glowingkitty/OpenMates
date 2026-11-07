import { get } from 'svelte/store';
import { currentPersonalDocumentMemories } from '../stores/personalDocumentMemories';
import { userProfile } from '../stores/userProfile';
import { parseRuleDocument, serializeRuleDocument } from '../utils/ruleDocuments';
import type { WikipediaArticleIdentity } from '../utils/wikipediaLearning';

const pendingSaves = new Map<string, Promise<string>>();
const MAX_TOPIC_CHARS = 160;

function interestBody(article: WikipediaArticleIdentity): string {
  return `Wikipedia (${article.language}): ${article.source_url}`;
}

/** Returns the id of the personal Memory that already records this article as a Study interest. */
export function findWikipediaStudyInterest(article: WikipediaArticleIdentity): string | null {
  for (const entry of currentPersonalDocumentMemories()) {
    const document = entry.item_value.document;
    if (typeof document !== 'string') continue;
    try {
      const fields = parseRuleDocument(document);
      if (fields.title.startsWith('Study interest: ') && fields.body.includes(article.source_url)) return entry.id;
    } catch {
      continue; // An invalid document can never be this interest.
    }
  }
  return null;
}

/** Saves the article as a personal Memory document that is only offered with approval (`ask_first`). */
export function saveWikipediaStudyInterest(article: WikipediaArticleIdentity): Promise<string> {
  const existing = findWikipediaStudyInterest(article);
  if (existing) return Promise.resolve(existing);
  const owner = get(userProfile).user_id;
  if (!owner) return Promise.reject(new Error('Login required to save a Study interest'));
  const key = `${owner}:${article.source_url}`;
  const pending = pendingSaves.get(key);
  if (pending) return pending;
  const save = (async () => {
    const { savePersonalRuleDocument, personalDocumentMemoryEntries } = await import('./ruleDocumentService');
    const topic = article.canonical_title.slice(0, MAX_TOPIC_CHARS);
    const rule = await savePersonalRuleDocument({
      document: serializeRuleDocument({
        title: `Study interest: ${topic}`,
        when_to_use: `When I ask what to study or learn next, or about ${topic}`,
        body: interestBody(article),
        load_mode: 'ask_first',
      }),
    });
    if (get(userProfile).user_id !== owner) throw new Error('Account changed while saving');
    await personalDocumentMemoryEntries(); // Publishes the new Memory for findWikipediaStudyInterest.
    return `account-memory-${rule.id.replace(/^personal:/, '')}`;
  })();
  pendingSaves.set(key, save);
  void save.finally(() => { pendingSaves.delete(key); }).catch(() => {});
  return save;
}
