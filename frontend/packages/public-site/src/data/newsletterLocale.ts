import locales from '../generated/newsletterLocale.generated.json';
export { newsletterKeys } from '../generated/newsletterKeys.generated';
export type { NewsletterKey } from '../generated/newsletterKeys.generated';
import type { NewsletterKey } from '../generated/newsletterKeys.generated';

export function newsletterText(locale: 'en' | 'de', key: NewsletterKey): string {
  const lookup = (language: 'en' | 'de') => {
    const value = (locales[language] as Record<string, unknown>)[key];
    return typeof value === 'string' ? value : value && typeof value === 'object' && 'text' in value ? String((value as { text: unknown }).text) : undefined;
  };
  const text = lookup(locale) ?? lookup('en');
  if (!text) throw new Error(`Missing public newsletter copy: ${locale}.${key}`);
  return text;
}
