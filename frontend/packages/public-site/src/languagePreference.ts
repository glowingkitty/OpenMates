/** Locale negotiation shared by the public website and the offline-first web app.
 * Only language codes are persisted; this preference is never an authentication signal.
 */
export type LanguagePreference = { mode: 'manual' | 'account'; language: string } | { mode: 'auto' };
export const LANGUAGE_STORAGE_KEY = 'preferredLanguage';
export const LANGUAGE_MODE_KEY = 'openmatesLanguageMode';
export const ACCOUNT_LANGUAGE_KEY = 'openmatesAccountLanguage';

export function normalizeLanguage(value: string | null | undefined, supported: readonly string[]): string | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase().replaceAll('_', '-');
  if (supported.includes(normalized)) return normalized;
  const base = normalized.split('-')[0];
  return supported.includes(base) ? base : null;
}

export function negotiateLanguage(value: string | readonly string[] | null | undefined, supported: readonly string[], fallback = 'en'): string {
  const entries = typeof value === 'string' ? value.split(',') : value ?? [];
  const ranked = entries.map((entry, order) => {
    const [tag, ...parameters] = entry.trim().split(';');
    const weight = parameters.find(parameter => parameter.trim().startsWith('q='));
    const quality = weight ? Number(weight.trim().slice(2)) : 1;
    return { language: normalizeLanguage(tag, supported), quality, order };
  }).filter(entry => entry.language && Number.isFinite(entry.quality) && entry.quality > 0 && entry.quality <= 1)
    .sort((left, right) => right.quality - left.quality || left.order - right.order);
  return ranked[0]?.language ?? fallback;
}

export function languageCookieName(hostname: string): string {
  return /(^|\.)dev\.openmates\.org$/.test(hostname) ? 'om_language_dev' : 'om_language';
}

export function parseLanguagePreference(value: string | null | undefined): LanguagePreference | null {
  if (value === 'auto') return { mode: 'auto' };
  const match = /^(manual|account):([a-z]{2,3}(?:-[a-z0-9]+)*)$/.exec(value ?? '');
  return match ? { mode: match[1] as 'manual' | 'account', language: match[2] } : null;
}

export function readLanguageCookie(cookies: string, hostname: string): LanguagePreference | null {
  const name = languageCookieName(hostname);
  const value = cookies.split(';').map(part => part.trim()).find(part => part.startsWith(`${name}=`))?.slice(name.length + 1);
  try { return parseLanguagePreference(decodeURIComponent(value ?? '')); } catch { return null; }
}

export function resolveLanguage(options: {
  urlLanguage?: string | null;
  preference?: LanguagePreference | null;
  browserLanguages?: string | readonly string[] | null;
  supported: readonly string[];
  fallback?: string;
}): string {
  return normalizeLanguage(options.urlLanguage, options.supported)
    ?? (options.preference && options.preference.mode !== 'auto' ? normalizeLanguage(options.preference.language, options.supported) : null)
    ?? negotiateLanguage(options.browserLanguages, options.supported, options.fallback);
}

/** Read-only migration: old saved preferredLanguage values remain manual choices. */
export function readBrowserPreference(): LanguagePreference | null {
  if (typeof window === 'undefined') return null;
  const cookie = readLanguageCookie(document.cookie, window.location.hostname);
  if (cookie && cookie.mode !== 'account') return cookie;
  try {
    if (localStorage.getItem(LANGUAGE_MODE_KEY) === 'auto') return { mode: 'auto' };
    const manual = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (manual) return { mode: 'manual', language: manual };
    const account = localStorage.getItem(ACCOUNT_LANGUAGE_KEY);
    return cookie ?? (account ? { mode: 'account', language: account } : null);
  } catch { return cookie; }
}

export function saveBrowserPreference(preference: LanguagePreference): void {
  if (typeof window === 'undefined') return;
  try {
    if (preference.mode === 'account') {
      localStorage.setItem(ACCOUNT_LANGUAGE_KEY, preference.language);
    } else if (preference.mode === 'auto') {
      localStorage.setItem(LANGUAGE_MODE_KEY, 'auto');
      localStorage.removeItem(LANGUAGE_STORAGE_KEY);
    } else {
      localStorage.setItem(LANGUAGE_MODE_KEY, 'manual');
      localStorage.setItem(LANGUAGE_STORAGE_KEY, preference.language);
    }
  } catch { /* Browser storage can be disabled; the current selection still works. */ }
  const hostname = window.location.hostname;
  const domain = /(^|\.)dev\.openmates\.org$/.test(hostname) ? 'dev.openmates.org'
    : /(^|\.)openmates\.org$/.test(hostname) ? 'openmates.org' : null;
  const value = preference.mode === 'auto' ? 'auto' : `${preference.mode}:${preference.language}`;
  document.cookie = `${languageCookieName(hostname)}=${encodeURIComponent(value)}; Path=/; Max-Age=31536000; SameSite=Lax${domain ? `; Domain=${domain}` : ''}${window.location.protocol === 'https:' ? '; Secure' : ''}`;
}
