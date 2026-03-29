import { chatDB } from "./services/db";
import { userDB } from "./services/userDB";
import { loadUserProfileFromDB } from "./stores/userProfile";
import { authStore } from "./stores/authStore";
import { logCollector } from "./services/logCollector";
// Import userActionTracker to ensure passive DOM-event tracking starts at app load.
// The singleton attaches its listeners on instantiation — no explicit init call needed.
import { userActionTracker } from "./services/userActionTracker";
import { initDebugUtils } from "./services/debugUtils";
import { initPermissionDialogListener } from "./stores/appSettingsMemoriesPermissionStore";

/**
 * Initialize all application services
 * @param {Object} options - Configuration options
 * @param {boolean} options.skipAuthInitialization - If true, skip auth initialization (default: false)
 */
export async function initializeApp(
  options = { skipAuthInitialization: false },
) {
  console.debug("Initializing application...");

  try {
    // Initialize console log collector and user action tracker — both are singletons that
    // start intercepting events immediately on import (constructor side effects).
    // The void references prevent tree-shaking from stripping the imports as unused.
    void logCollector;
    void userActionTracker;

    // Initialize debug utilities for browser console access
    // These allow inspecting IndexedDB data via window.debugChat(), etc.
    initDebugUtils();

    // Initialize OpenTelemetry distributed tracing as early as possible so that
    // database init, auth, and all subsequent fetch() calls are instrumented.
    // getApiUrl() is a pure function based on compile-time VITE_* env vars —
    // it does NOT depend on auth state or any runtime initialization.
    try {
      const { getApiUrl } = await import("./config/api");
      const { initTracing } = await import("./services/tracing/setup");
      initTracing(getApiUrl());
      console.info("[App] OTel tracing initialized");
    } catch (err) {
      console.warn("[App] OTel tracing not available:", err);
    }

    // Initialize databases
    await chatDB.init();
    await userDB.init();

    // First load user profile from IndexedDB for immediate display
    await loadUserProfileFromDB();

    // Initialize app settings/memories permission dialog listener
    // This listens for "showAppSettingsMemoriesPermissionDialog" events from the WebSocket handler
    initPermissionDialogListener();

    // Check authentication only if not skipped
    if (!options.skipAuthInitialization) {
      console.debug("Performing auth initialization in initializeApp");
      await authStore.initialize();
    } else {
      console.debug("Skipping auth initialization in initializeApp");
    }

    console.debug("Application initialization complete");
  } catch (error) {
    console.error("Error initializing application:", error);
  }
}
