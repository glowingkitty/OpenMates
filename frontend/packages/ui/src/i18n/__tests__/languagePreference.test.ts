import { beforeEach, describe, expect, it, vi } from 'vitest';
import { normalizeLanguage, negotiateLanguage, resolveLanguage, readLanguageCookie, languageCookieName, readBrowserPreference, saveBrowserPreference } from '@repo/public-site/languagePreference';

const supported = ['en', 'de', 'fr', 'ar'];
describe('language preference negotiation', () => {
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.manual-choice
  it.each(['de-DE', 'de-AT', 'de_CH', 'DE'])('normalizes regional browser tag %s', value => {
    expect(normalizeLanguage(value, supported)).toBe('de');
  });
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.manual-choice
  it('selects the highest weighted supported browser language', () => {
    expect(negotiateLanguage('xx;q=1,en;q=0.5,de-AT;q=0.9', supported)).toBe('de');
    expect(negotiateLanguage(['xx', 'fr-CA', 'de-DE'], supported)).toBe('fr');
    expect(negotiateLanguage('de;q=0,en;q=0.1', supported)).toBe('en');
  });
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.manual-choice
  it('falls back safely for unavailable, malformed or excluded languages', () => {
    expect(negotiateLanguage('xx,de;q=NaN,fr;q=2', supported)).toBe('en');
  });
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.manual-choice
  it('gives page choice priority over manual preference and browser language', () => {
    expect(resolveLanguage({ urlLanguage: 'fr-CA', preference: { mode: 'manual', language: 'en' }, browserLanguages: ['de-DE'], supported })).toBe('fr');
    expect(resolveLanguage({ preference: { mode: 'manual', language: 'en' }, browserLanguages: ['de-DE'], supported })).toBe('en');
  });
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.manual-choice
  it('honors Automatic and restores an account locale when supplied', () => {
    expect(resolveLanguage({ preference: { mode: 'auto' }, browserLanguages: ['de-DE'], supported })).toBe('de');
    expect(resolveLanguage({ preference: { mode: 'account', language: 'fr' }, browserLanguages: ['de-DE'], supported })).toBe('fr');
  });
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.manual-choice
  it('isolates development cookies from production', () => {
    expect(languageCookieName('app.dev.openmates.org')).toBe('om_language_dev');
    expect(languageCookieName('app.openmates.org')).toBe('om_language');
    expect(readLanguageCookie('om_language=manual%3Aen; om_language_dev=manual%3Ade', 'landing.dev.openmates.org')).toEqual({ mode: 'manual', language: 'de' });
    expect(readLanguageCookie('om_language=%E0%A4%A', 'openmates.org')).toBeNull();
  });
});

describe('browser language preference persistence', () => {
  beforeEach(() => {
    localStorage.clear();
    document.cookie = 'om_language=; Max-Age=0; Path=/';
  });
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.manual-choice
  it('keeps a legacy saved language as an explicit choice', () => {
    localStorage.setItem('preferredLanguage', 'de');
    expect(readBrowserPreference()).toEqual({ mode: 'manual', language: 'de' });
  });
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.manual-choice
  it('can return from a manual choice to Automatic', () => {
    saveBrowserPreference({ mode: 'manual', language: 'en' });
    saveBrowserPreference({ mode: 'auto' });
    expect(readBrowserPreference()).toEqual({ mode: 'auto' });
    expect(localStorage.getItem('preferredLanguage')).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.manual-choice
  it('shares a new manual choice through the cookie', () => {
    saveBrowserPreference({ mode: 'manual', language: 'de' });
    localStorage.clear();
    expect(readBrowserPreference()).toEqual({ mode: 'manual', language: 'de' });
  });
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.first-paint
  it('retains the account cookie when browser storage cannot be read', () => {
    document.cookie = 'om_language=account%3Ade; Path=/';
    const storage = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('Storage unavailable', 'SecurityError');
    });
    try {
      expect(resolveLanguage({ preference: readBrowserPreference(), browserLanguages: ['en-US'], supported })).toBe('de');
    } finally { storage.mockRestore(); }
  });
});
