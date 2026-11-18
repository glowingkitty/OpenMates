// frontend/packages/ui/src/stores/accountSuspension.ts
// Holds the suspension details the API returns at login or in a 403 (code "account_suspended")
// so the suspended-account screen can show the reason and the appeal. The appeal token is
// short-lived and kept in memory only.
import { writable } from "svelte/store";

export interface AccountSuspensionDetail {
  code: "account_suspended";
  state: "temporary" | "pending_review";
  until: string | null;
  message: string;
  category?: string | null;
  appeal_token?: string | null;
}

export const accountSuspension = writable<AccountSuspensionDetail | null>(null);

/** Store the suspension when the payload is an account_suspended detail; returns true if it was. */
export function captureAccountSuspension(payload: unknown): boolean {
  const detail = (payload as { account_suspension?: unknown; detail?: unknown } | null);
  const candidate = (detail?.account_suspension ?? detail?.detail ?? payload) as Partial<AccountSuspensionDetail> | null;
  if (!candidate || candidate.code !== "account_suspended") return false;
  accountSuspension.set(candidate as AccountSuspensionDetail);
  return true;
}

let observerInstalled = false;

/**
 * Wrap window.fetch once so any 403 that carries an account_suspended detail (any API call,
 * not just login) opens the suspended-account screen. The original response is returned
 * untouched; only a clone is read.
 */
export function installAccountSuspensionObserver(): void {
  if (observerInstalled || typeof window === "undefined") return;
  observerInstalled = true;
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const response = await originalFetch(input, init);
    if (response.status === 403) {
      try {
        captureAccountSuspension(await response.clone().json());
      } catch {
        // Not a JSON body: an ordinary 403, nothing to capture.
      }
    }
    return response;
  };
}
