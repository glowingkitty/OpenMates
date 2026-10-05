/** Public article identity shared by the inline link, fullscreen and Study memory. */
export interface WikipediaArticleIdentity {
  canonical_title: string;
  language: string;
  source_url: string;
}

export interface WikipediaRelatedArticle {
  title: string;
  canonical_title: string;
  language: string;
  description?: string;
}

export interface WikipediaLearningBundle extends WikipediaArticleIdentity {
  questions: string[];
  related_articles: WikipediaRelatedArticle[];
  expires_in_seconds: number;
}

export function normalizeWikipediaName(value: string): string {
  return value.normalize('NFKC').replaceAll('_', ' ').replace(/\s*\([^()]*\)\s*$/, '')
    .replace(/\s+/g, ' ').trim().toLowerCase();
}

export function wikipediaNameMatches(label: string, title: string): boolean {
  return !!normalizeWikipediaName(label) && normalizeWikipediaName(label) === normalizeWikipediaName(title);
}

export function wikipediaArticleIdentity(title: string, language: string): WikipediaArticleIdentity {
  const canonicalTitle = title.replaceAll('_', ' ');
  return {
    canonical_title: canonicalTitle,
    language,
    source_url: `https://${language}.wikipedia.org/wiki/${encodeURIComponent(canonicalTitle.replaceAll(' ', '_'))}`,
  };
}
