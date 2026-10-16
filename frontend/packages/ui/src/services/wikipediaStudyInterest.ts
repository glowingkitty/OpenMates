import { get } from 'svelte/store';
import { appSettingsMemoriesStore } from '../stores/appSettingsMemoriesStore';
import { userProfile } from '../stores/userProfile';
import type { WikipediaArticleIdentity } from '../utils/wikipediaLearning';

const pendingSaves = new Map<string, Promise<string>>();
const exactTitle = (title: string) => title.normalize('NFKC').replaceAll('_', ' ').replace(/\s+/g, ' ').trim().toLowerCase();

export function findWikipediaStudyInterest(article: WikipediaArticleIdentity): string | null {
  for (const entry of get(appSettingsMemoriesStore).decryptedEntries.values()) {
    if (entry.app_id !== 'study' || entry.settings_group !== 'learning_goals') continue;
    const reference = entry.item_value._wikipedia as Partial<WikipediaArticleIdentity> | undefined;
    if (reference?.language === article.language && (reference.source_url === article.source_url
      || (reference.canonical_title && exactTitle(reference.canonical_title) === exactTitle(article.canonical_title)))) return entry.id;
    // Existing goals without an article reference can be reused by exact topic name.
    if (!reference && typeof entry.item_value.topic === 'string'
      && exactTitle(entry.item_value.topic) === exactTitle(article.canonical_title)) return entry.id;
  }
  return null;
}

/** Uses the existing client encryption and memory sync; no new memory permission is granted. */
export function saveWikipediaStudyInterest(article: WikipediaArticleIdentity): Promise<string> {
  const existing = findWikipediaStudyInterest(article);
  if (existing) return Promise.resolve(existing);
  const owner = get(userProfile).user_id;
  if (!owner) return Promise.reject(new Error('Login required to save a Study interest'));
  const key = `${owner}:${article.source_url}`;
  const pending = pendingSaves.get(key);
  if (pending) return pending;
  const save = (async () => {
    await appSettingsMemoriesStore.createEntry('study', {
      item_key: `wiki-${crypto.randomUUID()}`,
      settings_group: 'learning_goals',
      item_value: { topic: article.canonical_title, _wikipedia: article },
    });
    if (get(userProfile).user_id !== owner) throw new Error('Account changed while saving');
    const id = findWikipediaStudyInterest(article);
    if (!id) throw new Error('Study interest was not saved');
    return id;
  })();
  pendingSaves.set(key, save);
  void save.finally(() => { pendingSaves.delete(key); }).catch(() => {});
  return save;
}
