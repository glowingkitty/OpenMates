/** Lightweight anonymous client identity shared with chat storage and startup guards. */
export const ANONYMOUS_ID_STORAGE = 'openmates_anonymous_id';

/** Preserve the existing persisted identity and storage failure behavior. */
export function getAnonymousClientId(): string {
  let anonymousId = localStorage.getItem(ANONYMOUS_ID_STORAGE);
  if (!anonymousId) {
    anonymousId = crypto.randomUUID();
    localStorage.setItem(ANONYMOUS_ID_STORAGE, anonymousId);
  }
  return anonymousId;
}
