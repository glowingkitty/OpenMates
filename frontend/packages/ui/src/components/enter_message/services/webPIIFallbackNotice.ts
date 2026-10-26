/** One explanatory notice per browser tab/session; stores no private content. */
const STORAGE_KEY = 'openmates.pii.basic-notice.v1';
let shownInMemory = false;

export function claimWebPIIFallbackNotice(): boolean {
  if (shownInMemory) return false;
  shownInMemory = true;
  try {
    if (sessionStorage.getItem(STORAGE_KEY) === '1') return false;
    sessionStorage.setItem(STORAGE_KEY, '1');
  } catch {
    // Storage-denied/private browsing still gets only one notice per page.
  }
  return true;
}
