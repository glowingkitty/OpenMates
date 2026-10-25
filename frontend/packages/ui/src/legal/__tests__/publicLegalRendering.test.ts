import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { compilePublicLocales } from '../../../../public-site/scripts/compile-public-locales.mjs';
import { buildPrivacyPolicyContent, buildTermsOfUseContent } from '../../../../public-site/src/legal/buildLegalContent';

// Compile authored sources in memory: no generated files or product requests.
const { localeData } = compilePublicLocales(resolve(process.cwd(), '../../..'));

function translate(locale: 'en' | 'de', key: string): string {
  let value: unknown = localeData[locale];
  for (const part of key.split('.')) {
    value = value && typeof value === 'object' ? (value as Record<string, unknown>)[part] : undefined;
  }
  if (value && typeof value === 'object' && 'text' in value) value = (value as { text: unknown }).text;
  if (typeof value !== 'string') throw new Error(`Missing ${locale} legal translation: ${key}`);
  return value;
}

describe('public legal content built from authored translations', () => {
  // contract-test: supporting surface=gui.web assertions=settings-ui.localization.visible-content-resolves
  it.each(['en', 'de'] as const)('renders complete %s privacy with a textual no-training status', locale => {
    expect(translate(locale, 'legal.privacy.training_policies.status_no_training')).toBe(locale === 'en' ? 'No' : 'Nein');
    const body = buildPrivacyPolicyContent(key => translate(locale, key), {
      lastUpdated: '2026-10-22T00:00:00Z', locale,
    });
    expect(body).toContain('YouTube');
    expect(body).toContain('media.ccc.de');
    expect(body).not.toContain('[T:');
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.localization.visible-content-resolves
  it.each(['en', 'de'] as const)('preserves complete %s terms rendering', locale => {
    expect(buildTermsOfUseContent(key => translate(locale, key), {
      lastUpdated: '2026-10-22T00:00:00Z', locale,
    }).length).toBeGreaterThan(1000);
  });
});
