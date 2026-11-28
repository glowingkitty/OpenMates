/**
 * Connected-account provider/App id normalization shared by the CLI.
 * Mirrors the Rust core (account/connected_accounts.rs) and the web storage service.
 */

/** Web stores Google Calendar accounts as `google_calendar`; both mean `google`. */
export function normalizeConnectedAccountProviderId(providerId: string): string {
  return providerId === "google_calendar" ? "google" : providerId;
}

export function normalizeConnectedAccountAppId(appId: string): string {
  return appId === "google_calendar" ? "calendar" : appId;
}

/** App id a decrypted permissions envelope grants for the requested App. */
export function resolveConnectedAccountAppId(permissions: unknown, requestedAppId: string): string {
  const wanted = normalizeConnectedAccountAppId(requestedAppId);
  if (!permissions || typeof permissions !== "object" || Array.isArray(permissions)) return wanted;
  const envelope = permissions as Record<string, unknown>;
  const apps = envelope.apps;
  if (apps && typeof apps === "object" && !Array.isArray(apps)
    && Object.keys(apps).some((key) => normalizeConnectedAccountAppId(key) === wanted)) {
    return wanted;
  }
  if (envelope.app_id == null && apps && typeof apps === "object" && !Array.isArray(apps)) return "";
  return normalizeConnectedAccountAppId(String(envelope.app_id ?? wanted));
}

export function connectedAccountMissingMessage(providerId: string): string {
  const provider = normalizeConnectedAccountProviderId(providerId);
  if (provider === "google") {
    return "No google connected account found. Connect Google Calendar in the web app (Settings > Apps > Calendar) first.";
  }
  return `No ${provider} connected account found. Run \`openmates connect-account ${provider.replace(/_/g, "-")}\` first.`;
}
