import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { locale } from 'svelte-i18n';
import { applyAccountLanguage, setAppLanguagePreference, getDetectedBrowserLanguage } from '../setup';
import { readBrowserPreference } from '@repo/public-site/languagePreference';

beforeEach(() => {
  localStorage.clear();
  document.cookie = 'om_language=; Max-Age=0; Path=/';
  window.history.replaceState(null, '', '/');
});

describe('language restoration and user choices', () => {
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.manual-choice
  it('does not let a late account dictionary overwrite a newer manual selection', async () => {
    const accountRestore = applyAccountLanguage('fr');
    const choice = setAppLanguagePreference('en');
    await Promise.all([accountRestore, choice]);
    expect(get(locale)).toBe('en');
    expect(readBrowserPreference()).toEqual({ mode: 'manual', language: 'en' });
  });
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.manual-choice
  it('does not overwrite an explicit Automatic choice during account restoration', async () => {
    Object.defineProperty(navigator, 'languages', { configurable: true, value: ['de-DE'] });
    expect(getDetectedBrowserLanguage()).toBe('de');
    const accountRestore = applyAccountLanguage('fr');
    expect(await setAppLanguagePreference('auto')).toBe('de');
    await accountRestore;
    expect(get(locale)).toBe('de');
    expect(readBrowserPreference()).toEqual({ mode: 'auto' });
  });
  // contract-test: supporting surface=gui.web assertions=language-preferences.resolution,language-preferences.manual-choice
  it('a selector change supersedes an incoming URL hint', async () => {
    window.history.replaceState(null, '', '/?lang=de#settings/interface/language');
    await setAppLanguagePreference('en');
    expect(new URL(window.location.href).searchParams.has('lang')).toBe(false);
    expect(window.location.hash).toBe('#settings/interface/language');
    await applyAccountLanguage('de');
    expect(get(locale)).toBe('en');
  });
});
