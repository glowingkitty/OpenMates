/**
 * frontend/packages/ui/src/services/tracing/config.ts
 *
 * Configuration constants for the browser OpenTelemetry SDK.
 * Kept in a separate file so setup.ts and wsSpans.ts can
 * reference the same values without circular imports.
 *
 * The OTLP traces path is relative -- the API base URL is
 * prepended at runtime by setup.ts.
 */

/** Service name reported to the OTel backend (resource attribute). */
export const TRACING_SERVICE_NAME = 'web-app';

/** Relative path to the OTLP proxy endpoint on the API gateway. */
export const OTLP_TRACES_PATH = '/v1/telemetry/traces';

/**
 * URL patterns to exclude from fetch auto-instrumentation.
 * Tracing the OTLP export requests themselves would create
 * an infinite feedback loop.
 */
export const TRACING_IGNORE_URLS = [/\/v1\/telemetry\//];
