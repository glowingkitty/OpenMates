import { register, init, addMessages, locale, waitLocale } from "svelte-i18n";
import { writable } from "svelte/store";
import { tick } from "svelte";
import { normalizeLanguage, negotiateLanguage, resolveLanguage, readBrowserPreference, saveBrowserPreference, type LanguagePreference } from "@repo/public-site/languagePreference";
import { readCachedAccountLanguage } from "./cachedAccountLanguage";
import { browser } from "$app/environment";
import { LANGUAGE_CODES, isRtlLanguage } from "./languages";
import { waitForTranslations } from "../stores/i18n";
import enMessages from "./locales/en.json";

/**
 * Dynamic locale import map using Vite's import.meta.glob
 * This automatically discovers all available locale files and only loads languages
 * that are defined in languages.json AND have corresponding JSON files
 */
const allLocaleFiles = import.meta.glob("./locales/*.json");

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildLocaleImportMap(): Record<string, () => Promise<any>> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const map: Record<string, () => Promise<any>> = {};

  // Build import map only for languages defined in languages.json
  for (const langCode of LANGUAGE_CODES) {
    const localePath = `./locales/${langCode}.json`;
    if (allLocaleFiles[localePath]) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      map[langCode] = allLocaleFiles[localePath] as () => Promise<any>;
    } else {
      console.warn(
        `Language ${langCode} is in languages.json but locale file ${localePath} does not exist`,
      );
    }
  }

  return map;
}

const localeImportMap = buildLocaleImportMap();

/**
 * Load locale data using static import map
 * This ensures Vite can statically analyze all imports at build time
 */
const loadLocaleData = async (locale: string) => {
  try {
    // Use static import map instead of template literal to ensure Vite can bundle it
    const importFn = localeImportMap[locale];
    if (!importFn) {
      console.warn(
        `Locale import not found for ${locale}, falling back to English`,
      );
      const enImport = localeImportMap["en"];
      if (!enImport) {
        throw new Error("English locale import not found in import map");
      }
      const module = await enImport();
      return module.default || module;
    }

    const module = await importFn();
    return module.default || module;
  } catch (e) {
    console.error(`Could not load locale data for ${locale}`, e);
    // Try English as fallback
    try {
      const enImport = localeImportMap["en"];
      if (enImport) {
        const module = await enImport();
        return module.default || module;
      }
    } catch (fallbackError) {
      console.error("Failed to load English locale as fallback", fallbackError);
    }
    return null;
  }
};

/** Use one resolution policy before the app exposes any translated text. */
export function getCurrentLanguage(): string {
  if (!browser) return "en";
  return resolveLanguage({
    urlLanguage: new URLSearchParams(window.location.search).get("lang"),
    preference: readBrowserPreference(),
    browserLanguages: navigator.languages?.length ? navigator.languages : [navigator.language],
    supported: LANGUAGE_CODES,
  });
}

export function getDetectedBrowserLanguage(): string {
  return browser ? negotiateLanguage(navigator.languages?.length ? navigator.languages : [navigator.language], LANGUAGE_CODES) : "en";
}

export const languagePreferenceMode = writable<LanguagePreference['mode']>(browser ? readBrowserPreference()?.mode ?? 'auto' : 'auto');

function updateDocumentLanguage(language: string): void {
  if (!browser) return;
  document.documentElement.lang = language;
  document.documentElement.dir = isRtlLanguage(language) ? 'rtl' : 'ltr';
}

/** Load first, then switch: the previous dictionary remains visible during a manual change. */
let userPreferenceGeneration = 0;
let pendingUserPreference: LanguagePreference | null = null;
async function applyLocale(language: string, stillCurrent = () => true): Promise<boolean> {
  if (language !== 'en') {
    const messages = await loadLocaleData(language);
    if (!messages) throw new Error(`Translations unavailable: ${language}`);
    addMessages(language, messages);
  }
  // svelte-i18n's locale.set can be asynchronous while a registered loader remains.
  // Flush the selected queue, then recheck intent before committing the locale.
  await waitLocale(language);
  if (!stillCurrent()) return false;
  await locale.set(language);
  await waitLocale(language);
  if (!stillCurrent()) return false;
  updateDocumentLanguage(language);
  return true;
}

export async function setAppLanguagePreference(choice: string): Promise<string> {
  const language = choice === 'auto' ? getDetectedBrowserLanguage() : normalizeLanguage(choice, LANGUAGE_CODES);
  if (!language) throw new Error('Unsupported language');
  const generation = ++userPreferenceGeneration;
  const preference: LanguagePreference = choice === 'auto' ? { mode: 'auto' } : { mode: 'manual', language };
  pendingUserPreference = preference;
  try {
    if (!await applyLocale(language, () => generation === userPreferenceGeneration)) return getCurrentLanguage();
    saveBrowserPreference(preference);
    languagePreferenceMode.set(preference.mode);
    // An explicit switch supersedes the incoming page hint for future restores/reloads.
    const url = new URL(window.location.href);
    if (url.searchParams.has('lang')) {
      url.searchParams.delete('lang');
      window.history.replaceState(window.history.state, '', url);
    }
    await tick();
    window.dispatchEvent(new CustomEvent('language-changed'));
    window.dispatchEvent(new CustomEvent('language-changed-complete'));
    return language;
  } finally {
    if (generation === userPreferenceGeneration) pendingUserPreference = null;
  }
}

/** Account restoration never overrides a current manual choice or explicit Automatic mode. */
export async function applyAccountLanguage(value: string | null | undefined): Promise<string> {
  const generation = userPreferenceGeneration;
  const preference = pendingUserPreference ?? readBrowserPreference();
  const requested = browser ? new URLSearchParams(window.location.search).get('lang') : null;
  const accountLanguage = normalizeLanguage(value, LANGUAGE_CODES);
  const language = resolveLanguage({
    urlLanguage: requested,
    preference: preference?.mode === 'manual' || preference?.mode === 'auto' ? preference
      : accountLanguage ? { mode: 'account', language: accountLanguage } : preference,
    browserLanguages: browser ? navigator.languages : [], supported: LANGUAGE_CODES,
  });
  const explicitPreference = (value: LanguagePreference | null) => value?.mode === 'manual' || value?.mode === 'auto' ? JSON.stringify(value) : null;
  const unchanged = () => generation === userPreferenceGeneration
    && explicitPreference(preference) === explicitPreference(pendingUserPreference ?? readBrowserPreference());
  if (!await applyLocale(language, unchanged)) return getCurrentLanguage();
  if (!requested && preference?.mode !== 'manual' && preference?.mode !== 'auto' && accountLanguage) {
    saveBrowserPreference({ mode: 'account', language: accountLanguage });
    languagePreferenceMode.set('account');
  }
  return language;
}

// Register all supported locales from languages.json immediately when module loads
// This ensures the i18n system is set up before any components try to use it
// We use LANGUAGE_CODES from languages.json as the single source of truth
addMessages("en", enMessages);

LANGUAGE_CODES.filter((locale) => locale !== "en").forEach((locale) => {
  register(locale, () => loadLocaleData(locale));
});

// Initialize i18n immediately when module loads (synchronous)
// This MUST happen before any component tries to use $_ or other i18n functions
// The init() call sets up the locale store and makes waitLocale() work properly
const initialLocale = browser ? getCurrentLanguage() : "en";
init({
  fallbackLocale: "en",
  initialLocale: initialLocale,
  warnOnMissingMessages: true,
});

// Update HTML lang + dir attributes to match the initial locale.
// - lang: prevents browser auto-translate from activating (avoids rendering bugs)
// - dir:  enables native browser RTL layout for right-to-left languages like Arabic
if (browser && typeof document !== "undefined") {
  document.documentElement.setAttribute("lang", initialLocale);
  document.documentElement.setAttribute(
    "dir",
    isRtlLanguage(initialLocale) ? "rtl" : "ltr",
  );
}

// Async function for explicit initialization if needed
// This is mainly for backwards compatibility - the init() above already ran
let startup: Promise<void> | null = null;
export async function setupI18n(): Promise<void> {
  startup ??= (async () => {
    const urlLanguage = normalizeLanguage(new URLSearchParams(window.location.search).get('lang'), LANGUAGE_CODES);
    const preference = readBrowserPreference();
    if (urlLanguage) {
      saveBrowserPreference({ mode: 'manual', language: urlLanguage });
      languagePreferenceMode.set('manual');
      await applyLocale(urlLanguage);
    } else if (!preference || preference.mode === 'account') {
      const cached = await readCachedAccountLanguage();
      if (cached) await applyAccountLanguage(cached);
    } else {
      // Also migrate a legacy localStorage selection to the server-readable cookie.
      saveBrowserPreference(preference);
    }
    await applyLocale(getCurrentLanguage());
    await waitForTranslations();
  })();
  return startup;
}
