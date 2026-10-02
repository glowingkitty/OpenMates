/** Environment-scoped host notification settings; never persist destinations. */
import type { RuntimeNotificationConfig } from "./serverHealth.js";

export function evaluateNotificationDestinationConfiguration(config: RuntimeNotificationConfig) {
  const configuredCount = [config.email, config.discordWebhookUrl, config.genericWebhook].filter(Boolean).length;
  return {
    id: "notifications.destination_configured",
    status: configuredCount >= 2 ? "passed" as const : "failed" as const,
    required: true,
    duration_ms: 0,
    ...(configuredCount < 2 ? {
      failureClass: "configuration",
      sanitized_reason: "notification_destination_or_fallback_missing",
    } : {}),
  };
}

export function resolveHostNotificationDestinations(
  value: (key: string) => string | undefined,
  deploymentMode: "official_cloud" | "self_host",
  serverEnvironment: "production" | "development",
) {
  // Imported Vault markers are not usable host credentials or destinations.
  const configured = (key: string): string | undefined => {
    const candidate = value(key)?.trim();
    return candidate && candidate !== "IMPORTED_TO_VAULT" ? candidate : undefined;
  };
  const to = configured("OPENMATES_RUNTIME_HEALTH_EMAIL_TO") || configured("ADMIN_NOTIFY_EMAIL");
  const from = configured("OPENMATES_RUNTIME_HEALTH_EMAIL_FROM") || configured("EMAIL_SENDER_EMAIL") || "noreply@openmates.org";
  const apiKey = configured("OPENMATES_RUNTIME_HEALTH_BREVO_API_KEY") || configured("BREVO_API_KEY");
  const email: RuntimeNotificationConfig["email"] = to && apiKey ? { to, from, apiKey } : undefined;
  const scopedDiscord = deploymentMode === "self_host"
    ? configured("DISCORD_WEBHOOK_OPERATIONAL_MONITORING_SELF_HOST") || configured("OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_SELF_HOST") || configured("OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL")
    : serverEnvironment === "production"
      ? configured("OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_PRODUCTION") || configured("DISCORD_WEBHOOK_OPERATIONAL_MONITORING_PRODUCTION")
      : configured("OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_DEVELOPMENT") || configured("DISCORD_WEBHOOK_OPERATIONAL_MONITORING_DEVELOPMENT");
  // Legacy cloud hosts can explicitly bind their existing destination to one
  // environment. An unscoped URL alone must never cross the prod/dev boundary.
  const legacyDiscord = deploymentMode === "official_cloud"
    && configured("OPENMATES_RUNTIME_HEALTH_LEGACY_DISCORD_ENVIRONMENT") === serverEnvironment
    ? configured("OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL")
    : undefined;
  const fallbackDiscord = deploymentMode === "self_host"
    ? undefined
    : serverEnvironment === "production"
      ? configured("DISCORD_WEBHOOK_PROD_SMOKE")
      : configured("DISCORD_WEBHOOK_DEV_NIGHTLY") || configured("DISCORD_WEBHOOK_DEV_SMOKE");
  const discordWebhookUrl = scopedDiscord || legacyDiscord || fallbackDiscord;
  return {
    email,
    discordWebhookUrl,
    discordDestinationSource: scopedDiscord ? "canonical" : legacyDiscord ? "legacy_environment_mapping"
      : fallbackDiscord ? serverEnvironment === "production" ? "prod_smoke_fallback" : "dev_fallback" : "missing",
    discordFallbackUsed: !scopedDiscord && !legacyDiscord && Boolean(fallbackDiscord),
  };
}
