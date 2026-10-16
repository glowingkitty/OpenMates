/**
 * Credentialless newsletter requests from the public website.
 * The API validates the browser's exact Origin and rate limits signup.
 * Category choices become durable only when the emailed token is confirmed.
 * No address, token, or result is saved in browser storage.
 */

export type NewsletterCategory = 'openmates_events' | 'software_updates' | 'apple_beta_updates';
export type NewsletterChoices = Record<NewsletterCategory, boolean>;
export type NewsletterLanguage = 'en' | 'de';

type NewsletterResult = { success: boolean; message?: string };

function endpoint(apiBaseUrl: string, path: string): string {
  return `${apiBaseUrl.replace(/\/$/, '')}${path}`;
}

async function readResult(response: Response): Promise<NewsletterResult> {
  const data: unknown = await response.json();
  if (!data || typeof data !== 'object' || !('success' in data)) {
    throw new Error('The newsletter service returned an unexpected response.');
  }
  const result = data as NewsletterResult;
  if (!response.ok || !result.success) {
    throw new Error(typeof result.message === 'string' ? result.message : 'The newsletter request failed.');
  }
  return result;
}

export async function requestNewsletterSubscription(
  apiBaseUrl: string,
  email: string,
  categories: NewsletterChoices,
  language: NewsletterLanguage,
  darkmode: boolean,
): Promise<NewsletterResult> {
  const response = await fetch(endpoint(apiBaseUrl, '/v1/newsletter/subscribe'), {
    method: 'POST',
    mode: 'cors',
    credentials: 'omit',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ email: email.trim(), language, darkmode, categories }),
  });
  return readResult(response);
}

export async function confirmNewsletterSubscription(apiBaseUrl: string, token: string): Promise<NewsletterResult> {
  const response = await fetch(endpoint(apiBaseUrl, `/v1/newsletter/confirm/${encodeURIComponent(token)}`), {
    method: 'GET',
    mode: 'cors',
    credentials: 'omit',
    headers: { Accept: 'application/json' },
  });
  return readResult(response);
}
