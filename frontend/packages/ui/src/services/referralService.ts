// frontend/packages/ui/src/services/referralService.ts
/**
 * Referral program client helpers.
 * Captures public #ref URL fragments locally, then submits them only after the
 * user is authenticated so referral codes are never sent to hosting providers
 * through query strings or server-side request logs.
 */

import { writable } from "svelte/store";
import { apiEndpoints, getApiEndpoint } from "../config/api";

const PENDING_REFERRAL_KEY = "openmates_pending_referral_code";
const REFERRAL_CODE_PATTERN = /^[A-Za-z0-9]{4,32}$/;

export interface ReferralStatus {
  available: boolean;
  referral_code: string | null;
  successful_referrals_count: number;
  max_successful_referrals: number;
  credits_per_referrer: number;
  credits_per_referred_user: number;
  min_purchase_amount_cents: number;
  attribution_expires_days: number;
}

export const referralStatus = writable<ReferralStatus | null>(null);

function parseReferralCodeFromHash(): string | null {
  if (typeof window === "undefined") return null;
  const hash = window.location.hash || "";
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  const code = params.get("ref");
  if (!code || !REFERRAL_CODE_PATTERN.test(code)) return null;
  return code.toUpperCase();
}

export function captureReferralCodeFromUrl(): void {
  if (typeof window === "undefined" || typeof sessionStorage === "undefined") return;
  const code = parseReferralCodeFromHash();
  if (!code) return;
  sessionStorage.setItem(PENDING_REFERRAL_KEY, code);

  const hash = window.location.hash || "";
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  params.delete("ref");
  const nextHash = params.toString();
  const nextUrl = `${window.location.pathname}${window.location.search}${nextHash ? `#${nextHash}` : ""}`;
  window.history.replaceState(null, "", nextUrl);
}

export async function submitPendingReferralCode(): Promise<void> {
  if (typeof sessionStorage === "undefined") return;
  captureReferralCodeFromUrl();
  const code = sessionStorage.getItem(PENDING_REFERRAL_KEY);
  if (!code) return;

  try {
    const response = await fetch(getApiEndpoint(apiEndpoints.referrals.capture), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ referral_code: code }),
    });
    if (response.ok) {
      sessionStorage.removeItem(PENDING_REFERRAL_KEY);
    }
  } catch (error) {
    console.warn("[ReferralService] Failed to submit pending referral code", error);
  }
}

export async function loadReferralStatus(): Promise<ReferralStatus | null> {
  try {
    const response = await fetch(getApiEndpoint(apiEndpoints.referrals.status), {
      credentials: "include",
    });
    if (!response.ok) {
      referralStatus.set(null);
      return null;
    }
    const status = (await response.json()) as ReferralStatus;
    referralStatus.set(status);
    return status;
  } catch (error) {
    console.warn("[ReferralService] Failed to load referral status", error);
    referralStatus.set(null);
    return null;
  }
}
