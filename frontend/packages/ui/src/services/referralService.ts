// frontend/packages/ui/src/services/referralService.ts
/**
 * Referral program client helpers.
 * Captures public #ref URL fragments locally, then submits them only after the
 * user is authenticated so referral codes are never sent to hosting providers
 * through query strings or server-side request logs.
 */

import { writable } from "svelte/store";
import { apiEndpoints, getApiEndpoint } from "../config/api";
import { WorkspaceQueryCache, WorkspaceCacheDiscardedError } from "./workspaceQueryCache";
import { buildWorkBody, workClient, workDecide, type WorkRequest } from "./work/workRust";

// Flag-on builds decide the referral status path, capture body and status refusal
// in the shared Rust core Worker (`work` op, web_work/billing.rs); the constant
// folds to false otherwise, so flag-off keeps the original paths. The page keeps
// fetch, sessionStorage, the URL fragment handling (synchronous) and the cache.
const RUST_WORK = import.meta.env.VITE_OPENMATES_RUST_CORE === "1";

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
const statusCache = new WorkspaceQueryCache<ReferralStatus>({ ttlMs: 60_000, maxEntries: 1 });
statusCache.subscribe(() => queueMicrotask(() => referralStatus.set(statusCache.peek("status") ?? null)));

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
    const work = RUST_WORK ? workClient() : null;
    if (work) {
      const request = await workDecide<WorkRequest>(work, "referralCaptureBody", { code });
      const body = await buildWorkBody(request.steps, {}, {});
      const response = await fetch(getApiEndpoint(request.path), {
        method: request.method,
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      if (response.ok) {
        sessionStorage.removeItem(PENDING_REFERRAL_KEY);
        statusCache.invalidate("status");
        void loadReferralStatus();
      }
      return;
    }
    const response = await fetch(getApiEndpoint(apiEndpoints.referrals.capture), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ referral_code: code }),
    });
    if (response.ok) {
      sessionStorage.removeItem(PENDING_REFERRAL_KEY);
      statusCache.invalidate("status");
      void loadReferralStatus();
    }
  } catch (error) {
    console.warn("[ReferralService] Failed to submit pending referral code", error);
  }
}

export async function loadReferralStatus(): Promise<ReferralStatus | null> {
  try {
    const status = await statusCache.load("status", async () => {
      const work = RUST_WORK ? workClient() : null;
      if (work) {
        const path = await workDecide<string>(work, "referralStatusPath", {});
        const response = await fetch(getApiEndpoint(path), { credentials: "include" });
        await workDecide(work, "referralStatusResult", { ok: response.ok, status: response.status });
        return (await response.json()) as ReferralStatus;
      }
      const response = await fetch(getApiEndpoint(apiEndpoints.referrals.status), {
        credentials: "include",
      });
      if (!response.ok) throw new Error(`Referral status request failed: ${response.status}`);
      return (await response.json()) as ReferralStatus;
    });
    referralStatus.set(status);
    return status;
  } catch (error) {
    if (error instanceof WorkspaceCacheDiscardedError) return null;
    console.warn("[ReferralService] Failed to load referral status", error);
    if (!statusCache.peek("status")) referralStatus.set(null);
    return null;
  }
}
