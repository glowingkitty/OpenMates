// frontend/packages/ui/src/stores/pairSessionStore.ts
/**
 * Pair Session Store — tracks whether the current session was established via magic pair login.
 *
 * When a session is a "pair session" (logged in via QR/token from another device), it operates
 * in restricted mode to protect user security in untrusted environments (e.g., public computers).
 *
 * Restricted mode blocks:
 *   - Credit purchases
 *   - Data export (GDPR export)
 *   - Account deletion
 *   - Any security settings changes (read-only)
 *   - Memories sync (no sync to/from server in restricted sessions)
 *
 * Restricted mode hides these settings pages entirely:
 *   - Account (username, email, timezone, profile picture, security, storage, chats, delete)
 *   - Memories (app settings)
 *   - Security sub-pages (passkeys, password, 2FA, recovery key)
 *
 * Auto-logout timer (optional, set by the authorizing device at pair time):
 *   - Stored in sessionStorage as { expiresAt: timestamp }
 *   - Local countdown — fires even without internet connectivity
 *   - Warning shown at 5 minutes before expiry
 *   - On expiry: calls standard logout (local state clear, then server logout if connected)
 *
 * Architecture: docs/architecture/device-sessions.md
 */

import { writable, derived, get } from "svelte/store";
import {
  authFlowActive,
  FAIL_CLOSED_PAIR_STATE,
  NEUTRAL_PAIR_STATE,
  pairActivate,
  pairAutoLogoutDue,
  pushPairView,
} from "../services/rustCore/auth/flowPush";

/** Flag builds: pair policy runs in the shared Rust core (see flowPush.ts). */
const RUST_FLOW: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === "1";

// ---------------------------------------------------------------------------
// Persistence keys
// ---------------------------------------------------------------------------

const STORAGE_KEY_PAIR_SESSION = "openmates_pair_session";
const STORAGE_KEY_AUTO_LOGOUT = "openmates_pair_auto_logout";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PairSessionData {
  /** Whether this session was established via magic pair login */
  isPairSession: boolean;
  /** Unix timestamp (ms) when this pair session was established */
  establishedAt: number;
  /** Name of the device that authorized the pairing (shown in UI) */
  authorizerDeviceName: string | null;
  /** Auto-logout minutes (null = no auto-logout) */
  autoLogoutMinutes: number | null;
  /** Unix timestamp (ms) when auto-logout fires; null if disabled */
  autoLogoutAt: number | null;
}

export interface PairSessionState {
  isPairSession: boolean;
  authorizerDeviceName: string | null;
  autoLogoutAt: number | null;
  /** True when < 5 minutes remain before auto-logout */
  autoLogoutWarning: boolean;
  /** Remaining seconds until auto-logout (null if no auto-logout) */
  remainingSeconds: number | null;
}

// ---------------------------------------------------------------------------
// Store internals
// ---------------------------------------------------------------------------

const AUTO_LOGOUT_WARNING_SECONDS = 5 * 60; // 5 minutes before expiry

function _loadFromStorage(): PairSessionData | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY_PAIR_SESSION);
    if (!raw) return null;
    return JSON.parse(raw) as PairSessionData;
  } catch {
    return null;
  }
}

function _saveToStorage(data: PairSessionData | null): void {
  if (typeof window === "undefined") return;
  if (!data) {
    sessionStorage.removeItem(STORAGE_KEY_PAIR_SESSION);
    sessionStorage.removeItem(STORAGE_KEY_AUTO_LOGOUT);
    return;
  }
  sessionStorage.setItem(STORAGE_KEY_PAIR_SESSION, JSON.stringify(data));
  if (data.autoLogoutAt) {
    sessionStorage.setItem(STORAGE_KEY_AUTO_LOGOUT, String(data.autoLogoutAt));
  }
}

// Core writable store
const _pairSessionData = writable<PairSessionData | null>(_loadFromStorage());

/**
 * Flag builds: true from `activatePairSession` until Rust has built the record.
 * While it is set (or a stored record has no Rust view yet) the session counts
 * as restricted, so the pairing answer latency never opens a window.
 */
const _activationPending = writable<boolean>(false);

// Keep sessionStorage in sync
_pairSessionData.subscribe((data) => _saveToStorage(data));

// ---------------------------------------------------------------------------
// Derived state (recomputed every tick via separate reactive store)
// ---------------------------------------------------------------------------

/** Current timestamp store — updated every second when a pair session with auto-logout is active */
const _now = writable<number>(Date.now());

let _tickInterval: ReturnType<typeof setInterval> | null = null;

_pairSessionData.subscribe((data) => {
  if (data?.autoLogoutAt && typeof window !== "undefined") {
    // Start ticking if not already
    if (!_tickInterval) {
      _tickInterval = setInterval(() => {
        _now.set(Date.now());
        // Check if expired — trigger logout
        const d = get(_pairSessionData);
        if (RUST_FLOW && authFlowActive()) {
          if (d) {
            pairAutoLogoutDue(d, Date.now())
              .then((due) => { if (due) void _handleAutoLogout(); })
              .catch((e) => console.warn("[PairSession] Rust auto-logout check failed; session stays restricted:", e));
          }
        } else if (d?.autoLogoutAt && Date.now() >= d.autoLogoutAt) {
          _handleAutoLogout();
        }
      }, 1000);
    }
  } else {
    // Stop ticking if no auto-logout
    if (_tickInterval) {
      clearInterval(_tickInterval);
      _tickInterval = null;
    }
  }
});

// ---------------------------------------------------------------------------
// Auto-logout handler (injected at runtime to avoid circular imports)
// ---------------------------------------------------------------------------

let _logoutCallback: (() => Promise<void>) | null = null;
let _autoLogoutInFlight: Promise<void> | null = null;

/**
 * Register the logout callback from the auth system.
 * Must be called during app init (e.g., in +page.svelte) to enable auto-logout.
 */
export function registerPairLogoutCallback(
  callback: () => Promise<void>,
): void {
  _logoutCallback = callback;
}

async function _handleAutoLogout(): Promise<void> {
  if (_autoLogoutInFlight) return _autoLogoutInFlight;
  if (!_logoutCallback) {
    console.warn(
      "[PairSession] Auto-logout triggered but no logout callback registered",
    );
    return;
  }
  _autoLogoutInFlight = (async () => {
    try {
      await _logoutCallback!();
      // Keep restricted mode until key removal and local auth logout finish.
      _pairSessionData.set(null);
    } catch (e) {
      console.error("[PairSession] Auto-logout failed:", e);
      // The next timer tick retries cleanup while the restriction remains active.
    } finally {
      _autoLogoutInFlight = null;
    }
  })();
  return _autoLogoutInFlight;
}

// ---------------------------------------------------------------------------
// Exported derived store
// ---------------------------------------------------------------------------

/** Flag builds: Rust has answered for the current record, so ticks need not reset to restricted. */
let _rustViewKnown = false;

export const pairSessionState = RUST_FLOW && authFlowActive()
  ? derived(
      [_pairSessionData, _now, _activationPending],
      ([$data, $now, $pending], set: (value: PairSessionState) => void) => {
        // Fail closed: a record (or an activation in flight) is restricted until Rust's view arrives.
        if ($data || $pending) {
          if (!_rustViewKnown) set(FAIL_CLOSED_PAIR_STATE);
        } else {
          _rustViewKnown = false;
        }
        if (!$data) {
          if (!$pending) pushPairView(null, $now, set);
          return;
        }
        pushPairView($data, $now, (view) => { _rustViewKnown = true; set(view); });
      },
      NEUTRAL_PAIR_STATE,
    )
  : derived(
  [_pairSessionData, _now],
  ([$data, $now]): PairSessionState => {
    if (!$data?.isPairSession) {
      return {
        isPairSession: false,
        authorizerDeviceName: null,
        autoLogoutAt: null,
        autoLogoutWarning: false,
        remainingSeconds: null,
      };
    }

    let remainingSeconds: number | null = null;
    let autoLogoutWarning = false;

    if ($data.autoLogoutAt) {
      const remaining = Math.max(
        0,
        Math.floor(($data.autoLogoutAt - $now) / 1000),
      );
      remainingSeconds = remaining;
      autoLogoutWarning = remaining <= AUTO_LOGOUT_WARNING_SECONDS;
    }

    return {
      isPairSession: true,
      authorizerDeviceName: $data.authorizerDeviceName,
      autoLogoutAt: $data.autoLogoutAt,
      autoLogoutWarning,
      remainingSeconds,
    };
  },
);

/** Convenience derived: true when the session is restricted (= isPairSession) */
export const isRestrictedSession = derived(
  pairSessionState,
  ($s) => $s.isPairSession,
);

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

/**
 * Activate pair-session restricted mode after a successful pairing.
 * Called by the pair complete flow once the user has logged in.
 */
export function activatePairSession(opts: {
  authorizerDeviceName?: string | null;
  autoLogoutMinutes?: number | null;
  /** Absolute server deadline in Unix seconds. Numeric pair lifetimes must use this. */
  pairExpiresAt?: number | null;
}): void | Promise<void> {
  const now = Date.now();
  if (RUST_FLOW && authFlowActive()) {
    // The record is built in Rust and stored when the answer arrives.
    _activationPending.set(true);
    return pairActivate(opts, now).then((data) => {
      _pairSessionData.set(data);
      _activationPending.set(false);
    }).catch((e) => {
      // Stay restricted: the pending flag is not cleared when Rust cannot answer.
      console.error("[PairSession] Rust activation failed; session stays restricted:", e);
    });
  }
  const autoLogoutAt =
    opts.pairExpiresAt != null
      ? opts.pairExpiresAt * 1000
      : opts.autoLogoutMinutes != null
      ? now + opts.autoLogoutMinutes * 60 * 1000
      : null;

  const data: PairSessionData = {
    isPairSession: true,
    establishedAt: now,
    authorizerDeviceName: opts.authorizerDeviceName ?? null,
    autoLogoutMinutes: opts.autoLogoutMinutes ?? null,
    autoLogoutAt,
  };

  _pairSessionData.set(data);
}

/**
 * Rehydrate pair session from sessionStorage on page load.
 * Called once in +page.svelte after the app mounts.
 * Checks if an auto-logout already expired during the page reload.
 */
export async function rehydratePairSession(): Promise<void> {
  const data = _loadFromStorage();
  if (!data?.isPairSession) return;

  // If auto-logout already expired while the page was reloading → logout immediately
  let due: boolean;
  if (RUST_FLOW && authFlowActive()) {
    try {
      due = await pairAutoLogoutDue(data, Date.now());
    } catch (e) {
      // Unknown deadline: keep the stored record, which is restricted; the tick re-checks every second.
      console.warn("[PairSession] Rust deadline check failed on rehydrate; session stays restricted:", e);
      due = false;
    }
  } else {
    due = !!data.autoLogoutAt && Date.now() >= data.autoLogoutAt;
  }
  if (due) {
    await _handleAutoLogout();
    return;
  }

  _pairSessionData.set(data);
}

// ---------------------------------------------------------------------------
// Pending pair token (for deep link → SettingsSessionsConfirmPair handoff)
// ---------------------------------------------------------------------------

/**
 * Written by the onPair deep link handler in +page.svelte immediately before
 * navigating to account/security/sessions/confirm-pair.
 * Consumed by SettingsSessionsConfirmPair on mount and for replacement links
 * while that destination remains mounted.
 */
export const pendingPairToken = writable<string | null>(null);

/**
 * Set to true by SettingsSessionsConfirmPair when pairing completes successfully.
 * Read once by SettingsSessions to show a "New" badge on the newest session.
 * Cleared after the sessions list reads it.
 */
export const newlyPairedSession = writable<boolean>(false);
