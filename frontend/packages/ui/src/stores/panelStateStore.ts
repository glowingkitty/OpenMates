/* eslint-disable no-console */
import { writable, derived, get } from "svelte/store";
import { authStore } from "./authStore";
import { isInSignupProcess, isLoggingOut } from "./signupState";
import {
  isMobileView,
  isChatsDefaultOpenViewport,
  loginInterfaceOpen,
} from "./uiStateStore";

type ActivityHistoryUserIntent = "auto" | "closed" | "open";

// --- Internal Writable Stores ---
const _isActivityHistoryOpen = writable<boolean>(false);
const _isSettingsOpen = writable<boolean>(false);
const _activityHistoryUserIntent = writable<ActivityHistoryUserIntent>("auto");

// --- Actions ---

/**
 * Toggles the Activity History panel based on user interaction.
 * Updates the user intent.
 * CRITICAL: Does not allow opening during signup process or when login interface is open - panel must remain closed.
 */
function toggleChats(): void {
  const currentlyOpen = get(_isActivityHistoryOpen);
  const mobileView = get(isMobileView); // Get current mobile state
  const inSignupProcess = get(isInSignupProcess); // Check if user is in signup process
  const loginOpen = get(loginInterfaceOpen); // Check if login interface is open

  console.debug("[PanelState] toggleChats called:", {
    currentlyOpen,
    mobileView,
    inSignupProcess,
    loginOpen,
    timestamp: Date.now(),
  });

  // CRITICAL: Never allow opening during signup process - panel must remain closed
  if (inSignupProcess) {
    console.debug(
      "[PanelState] Blocked toggleChats - user is in signup process, panel must remain closed",
    );
    // Ensure panel is closed if somehow it got opened
    _isActivityHistoryOpen.set(false);
    _activityHistoryUserIntent.set("closed");
    return;
  }

  // CRITICAL: Never allow opening when login interface is open - panel must remain closed
  if (loginOpen) {
    console.debug(
      "[PanelState] Blocked toggleChats - login interface is open, panel must remain closed",
    );
    // Ensure panel is closed if somehow it got opened
    _isActivityHistoryOpen.set(false);
    _activityHistoryUserIntent.set("closed");
    return;
  }

  if (currentlyOpen) {
    // User is manually closing it
    console.debug("[PanelState] Closing chats panel");
    _activityHistoryUserIntent.set("closed");
    // Explicitly close on mobile for immediate effect, otherwise rely on derived store
    if (mobileView) {
      _isActivityHistoryOpen.set(false);
    }
    // Note: Derived store will still run and confirm false on mobile.
    // On desktop, derived store handles closing based on intent.
  } else {
    // User is manually opening it (overrides 'auto' logic temporarily)
    // Keep original logic for opening, as the header button seems to work.
    console.debug("[PanelState] Opening chats panel");
    _activityHistoryUserIntent.set("open"); // Persist explicit user-open action
    _isActivityHistoryOpen.set(true); // Force open immediately
  }
  // Note: The derived store will recalculate and might override the forced open/close
  // if conditions (like mobile view or signup process) dictate it.
}

/**
 * Explicitly opens the Activity History (Chats) panel.
 * Unlike toggleChats(), this works on mobile — used by Cmd+F search shortcut
 * so the sidebar opens even on narrow viewports to reveal the search bar.
 * Guards (signup process, login interface open) are still respected.
 */
function openChats(): void {
  const inSignupProcess = get(isInSignupProcess);
  const loginOpen = get(loginInterfaceOpen);

  if (inSignupProcess || loginOpen) {
    console.debug(
      "[PanelState] openChats blocked — signup or login interface active",
    );
    return;
  }

  // "open" intent bypasses the mobile guard in the derived store so the
  // panel mounts even on narrow viewports (e.g. Cmd+F from mobile).
  _activityHistoryUserIntent.set("open");
  _isActivityHistoryOpen.set(true);
}

/**
 * Opens the Settings panel.
 */
function openSettings(): void {
  _isSettingsOpen.set(true);
}

/**
 * Closes the Settings panel.
 */
function closeSettings(): void {
  _isSettingsOpen.set(false);
}

/**
 * Resets the user intent for Activity History, allowing auto-logic to take over.
 * Useful when conditions change (e.g., login/logout).
 */
function resetActivityHistoryIntent(): void {
  _activityHistoryUserIntent.set("auto");
}

// --- Derived State Logic ---

// Determine the *intended* state of Activity History based on conditions
const intendedActivityHistoryOpen = derived(
  [
    authStore,
    isInSignupProcess,
    isLoggingOut,
    isMobileView,
    isChatsDefaultOpenViewport,
    loginInterfaceOpen,
    _activityHistoryUserIntent,
  ],
  ([
    ,
    $isInSignupProcess,
    ,
    $isMobileView,
    $isChatsDefaultOpenViewport,
    $loginInterfaceOpen,
    $activityHistoryUserIntent,
  ]) => {
    // CHANGED: Allow non-authenticated users to see the sidebar (with demo chats)
    // Only close during signup process (NOT during logout - keep panel open to show demo chats)
    if ($isInSignupProcess) {
      console.debug("[PanelState] Intended AH Closed: In Signup Process");
      return false; // Must be closed during signup
    }
    // CRITICAL: Close panel when login interface is open (prevents opening on resize from mobile to desktop)
    if ($loginInterfaceOpen) {
      console.debug("[PanelState] Intended AH Closed: Login Interface Open");
      return false; // Must be closed when login interface is open
    }
    if ($isMobileView && $activityHistoryUserIntent !== "open") {
      console.debug("[PanelState] Intended AH Closed: Mobile View");
      return false; // Must be closed on mobile unless explicitly force-opened (e.g. Cmd+F)
    }
    if ($activityHistoryUserIntent === "closed") {
      console.debug("[PanelState] Intended AH Closed: User Manually Closed");
      return false; // Must be closed if user manually closed it
    }
    if ($activityHistoryUserIntent === "open") {
      console.debug("[PanelState] Intended AH Open: User Manually Opened");
      return true;
    }
    // Default behavior: open only on very wide screens.
    console.debug(
      "[PanelState] Intended AH based on viewport default-open rule",
      {
        isChatsDefaultOpenViewport: $isChatsDefaultOpenViewport,
      },
    );
    return $isChatsDefaultOpenViewport;
  },
);

// Determine the *intended* state of Settings
// NOTE: Non-authenticated users can access app_store and interface settings
// This allows them to browse apps and change language during signup
const intendedSettingsOpen = derived(
  [authStore, isInSignupProcess, isLoggingOut, _isSettingsOpen],
  ([, , $isLoggingOut, $isSettingsOpen]) => {
    // Allow settings to open for non-authenticated users (they can access app_store and interface)
    // Only block during logout
    if ($isLoggingOut) {
      console.debug("[PanelState] Intended Settings Closed: Logging out");
      return false; // Close settings if logging out
    }
    // Otherwise, respect the current state (_isSettingsOpen) set by actions
    // This allows non-authenticated users to open settings for app_store/interface
    return $isSettingsOpen;
  },
);

// --- Subscriptions to update actual state based on intended state ---
//
// IMPORTANT: These subscriptions are deferred via queueMicrotask to avoid a
// Temporal Dead Zone (TDZ) crash that occurs when this module is evaluated
// as part of a circular import chain through:
//   panelStateStore → authStore → authLoginLogoutActions → chatNavigationStore
//   → demo_chats → @repo/ui barrel (which re-exports panelStateStore)
//
// Because the @repo/ui barrel is still mid-evaluation when chatNavigationStore
// triggers re-entry, any `const` store declared after panelStateStore in the
// barrel is in the TDZ. Running subscriptions synchronously here causes V8 to
// throw "Cannot access '<store>' before initialization" when one of those
// not-yet-initialized stores is read indirectly.
//
// queueMicrotask defers execution until after the current synchronous module-
// evaluation stack has fully completed, at which point every module is
// initialized and the TDZ no longer applies.
queueMicrotask(() => {
  intendedActivityHistoryOpen.subscribe((intendedState) => {
    if (get(_isActivityHistoryOpen) !== intendedState) {
      console.debug(
        `[PanelState] Updating Activity History Open: ${get(_isActivityHistoryOpen)} -> ${intendedState}`,
      );
      _isActivityHistoryOpen.set(intendedState);
    }
  });

  intendedSettingsOpen.subscribe((intendedState) => {
    // Only close reactively. Opening is handled by explicit actions.
    if (!intendedState && get(_isSettingsOpen)) {
      console.debug(
        `[PanelState] Reactively Closing Settings: ${get(_isSettingsOpen)} -> ${intendedState}`,
      );
      _isSettingsOpen.set(false);
    }
    // We don't automatically open settings here, only close based on auth/logout state.
    // Actual opening happens via openSettings() action.
  });

  // Reset user intent when auth state changes significantly (login/logout)
  // Subscribe specifically to isAuthenticated and isLoggingOut
  derived([authStore, isLoggingOut], ([$authStore, $isLoggingOut]) => ({
    isAuthenticated: $authStore.isAuthenticated,
    isLoggingOut: $isLoggingOut,
  })).subscribe(() => {
    console.debug(
      "[PanelState] Auth state changed, resetting Activity History user intent to auto.",
    );
    resetActivityHistoryIntent();
  });

  // CRITICAL: Immediately close panel when signup process starts
  // This ensures the panel is closed even if it was opened before signup detection
  isInSignupProcess.subscribe((inSignup) => {
    if (inSignup) {
      console.debug(
        "[PanelState] Signup process started - immediately closing Activity History panel",
      );
      _isActivityHistoryOpen.set(false);
      _activityHistoryUserIntent.set("closed");
    }
  });

  // CRITICAL: Immediately close panel when login interface opens
  // This ensures the panel is closed even if it was opened before login interface detection
  // This prevents the panel from opening on resize from mobile to desktop when login interface is open
  loginInterfaceOpen.subscribe((loginOpen) => {
    if (loginOpen) {
      console.debug(
        "[PanelState] Login interface opened - immediately closing Activity History panel",
      );
      _isActivityHistoryOpen.set(false);
      _activityHistoryUserIntent.set("closed");
    }
  });
});

// --- Exports ---
export const panelState = {
  subscribe: derived(
    [_isActivityHistoryOpen, _isSettingsOpen],
    ([$_isActivityHistoryOpen, $_isSettingsOpen]) => ({
      isActivityHistoryOpen: $_isActivityHistoryOpen,
      isSettingsOpen: $_isSettingsOpen,
    }),
  ).subscribe,
  toggleChats,
  openChats,
  openSettings,
  closeSettings,
  // Expose reset for potential use elsewhere if needed, e.g., deep linking
  resetActivityHistoryIntent,
};

// Optional: Export individual states if needed directly elsewhere, though panelState is preferred
export const isActivityHistoryOpen = derived(
  _isActivityHistoryOpen,
  (state) => state,
);
export const isSettingsOpen = derived(_isSettingsOpen, (state) => state);
