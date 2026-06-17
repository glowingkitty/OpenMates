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
import { initConnectedAccountPermissionListener } from "./stores/connectedAccountPermissionStore";

async function installE2ETestHooks() {
  if (typeof window === "undefined") return;
  const hasE2EDebugToken =
    window.location.hash.includes("e2e-debug=") &&
    window.location.hash.includes("e2e-token=");
  const isDevHost =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1" ||
    window.location.hostname.endsWith(".dev.openmates.org");
  if (!hasE2EDebugToken || !isDevHost) return;

  const testWindow = window as unknown as {
    __openmatesE2ESeedChat?: (input: {
      chat: Record<string, unknown>;
      messages: Record<string, unknown>[];
    }) => Promise<{ chatId: string; messageCount: number }>;
  };

  testWindow.__openmatesE2ESeedChat = async ({ chat, messages }) => {
    const chatId = String(chat.chat_id || "");
    if (!chatId.startsWith("e2e-")) {
      throw new Error("E2E seed chat IDs must start with e2e-");
    }

    const { chatKeyManager } = await import("./services/encryption/ChatKeyManager");
    chatKeyManager.createKeyForNewChat(chatId);
    await chatDB.addChat(chat as Parameters<typeof chatDB.addChat>[0]);
    for (const message of messages) {
      await chatDB.saveMessage(message as Parameters<typeof chatDB.saveMessage>[0]);
    }
    window.dispatchEvent(new CustomEvent("localChatListChanged", { detail: { chat_id: chatId } }));
    return { chatId, messageCount: messages.length };
  };
}

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

    // Initialize OpenTelemetry distributed tracing.
    // Dev: all visitors submit traces (backend accepts without auth).
    // Prod: tracing starts after login for admins/debug users only —
    // see setAuthenticatedState() in authSessionActions.ts.
    try {
      const { isDevEnvironment, getApiUrl } = await import("./config/api");
      if (isDevEnvironment()) {
        const { initTracing } = await import("./services/tracing/setup");
        initTracing(getApiUrl());
        console.info("[App] OTel tracing initialized");
      }
    } catch (err) {
      console.warn("[App] OTel tracing not available:", err);
    }

    // Initialize databases
    await chatDB.init();
    await userDB.init();
    await installE2ETestHooks();

    // First load user profile from IndexedDB for immediate display
    await loadUserProfileFromDB();

    // Initialize app settings/memories permission dialog listener
    // This listens for "showAppSettingsMemoriesPermissionDialog" events from the WebSocket handler
    initPermissionDialogListener();
    initConnectedAccountPermissionListener();

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
