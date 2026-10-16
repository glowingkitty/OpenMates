import locales from '../generated/publicLocales.generated.json';

type Locale = 'en' | 'de';
export function legalTranslate(locale: Locale, key: string): string {
  const parts = key.split('.');
  let value: unknown = locales[locale];
  for (const part of parts) value = value && typeof value === 'object' ? (value as Record<string, unknown>)[part] : undefined;
  if (value && typeof value === 'object' && 'text' in value) value = (value as {text: unknown}).text;
  if (typeof value === 'string') return value;
  if (locale !== 'en') return legalTranslate('en', key);
  throw new Error(`Missing public legal translation: ${key}`);
}
