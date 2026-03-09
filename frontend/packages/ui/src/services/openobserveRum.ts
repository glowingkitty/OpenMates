/**
 * OpenObserve RUM Service
 *
 * Initializes the OpenObserve browser SDK for Real User Monitoring (RUM) and
 * structured log forwarding. Replaces the former clientLogForwarder which only
 * worked for admin users via a backend proxy. The SDK sends data directly from
 * the browser to OpenObserve for ALL users (with configurable session replay).
 *
 * Architecture context: docs/architecture/admin-console-log-forwarding.md
 *
 * Privacy guarantees:
 * - User identity is only set after successful authentication (setUser)
 * - Identity is cleared on logout (clearUser)
 * - No PII is included by default in RUM session data
 *
 * Note: The OpenObserve endpoint and credentials are public-safe (write-only
 * ingest key). No sensitive data can be read via the browser SDK credentials.
 */

import { PUBLIC_OPENOBSERVE_RUM_ENDPOINT } from "$env/static/public";

// SDK is loaded lazily so it doesn't block app boot
let rumSdk: typeof import("@openobserve/browser-rum") | null = null;
let logsSdk: typeof import("@openobserve/browser-logs") | null = null;
let initialized = false;

const SERVICE_NAME = "openmates-web";
const ORG = "default";

export interface OpenObserveRumUser {
  id: string;
  name?: string;
  email?: string;
}

async function loadSdks() {
  if (rumSdk && logsSdk) return;
  const [rum, logs] = await Promise.all([
    import("@openobserve/browser-rum"),
    import("@openobserve/browser-logs"),
  ]);
  rumSdk = rum;
  logsSdk = logs;
}

const openobserveRumService = {
  /**
   * Initialize the RUM + logs SDK. Call once at app startup.
   * No-op if already initialized or if the endpoint env var is not set.
   */
  async init(): Promise<void> {
    if (initialized) return;

    const endpoint = PUBLIC_OPENOBSERVE_RUM_ENDPOINT;
    if (!endpoint) {
      // OpenObserve endpoint not configured — RUM disabled (e.g. local dev without monitoring)
      return;
    }

    try {
      await loadSdks();
      if (!rumSdk || !logsSdk) return;

      rumSdk.openobserveRum.init({
        applicationId: SERVICE_NAME,
        clientToken: "placeholder", // OpenObserve uses endpoint auth, not tokens
        site: endpoint,
        service: SERVICE_NAME,
        organizationIdentifier: ORG,
        trackInteractions: true,
        trackResources: true,
        trackLongTasks: true,
        defaultPrivacyLevel: "mask-user-input",
      });

      logsSdk.openobserveLogs.init({
        clientToken: "placeholder",
        site: endpoint,
        service: SERVICE_NAME,
        organizationIdentifier: ORG,
        forwardConsoleLogs: ["error", "warn"],
        forwardErrorsToLogs: true,
      });

      initialized = true;
    } catch (err) {
      // RUM is non-critical; log but never throw
      console.warn("[OpenObserveRum] SDK init failed (non-fatal):", err);
    }
  },

  /**
   * Set the authenticated user context. Call after successful login/session restore.
   */
  setUser(user: OpenObserveRumUser): void {
    if (!initialized || !rumSdk || !logsSdk) return;
    rumSdk.openobserveRum.setUser({ id: user.id, name: user.name, email: user.email });
  },

  /**
   * Clear the user context. Call on logout.
   */
  clearUser(): void {
    if (!initialized || !rumSdk || !logsSdk) return;
    rumSdk.openobserveRum.clearUser();
  },

  /**
   * Start session recording (opt-in). Call after user consent if applicable.
   */
  startRecording(): void {
    if (!initialized || !rumSdk) return;
    rumSdk.openobserveRum.startSessionReplayRecording();
  },

  /**
   * Stop session recording.
   */
  stopRecording(): void {
    if (!initialized || !rumSdk) return;
    rumSdk.openobserveRum.stopSessionReplayRecording();
  },
};

export { openobserveRumService };
