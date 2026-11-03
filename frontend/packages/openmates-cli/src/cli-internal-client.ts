/**
 * CLI-internal entry for first-party OpenMates test harnesses and benchmarks.
 *
 * NOT an SDK entrypoint and not covered by SDK compatibility: it re-exports the
 * root package and overrides `OpenMatesClient` with the CLI's own session client,
 * which by design loads the stored CLI login of the current CLI state directory.
 * Third-party integrations use the API-key SDK (`openmates`, `openmates/sdk`).
 */
export * from "./index.js";
export { OpenMatesClient } from "./client.js";
export type { OpenMatesClientOptions } from "./client.js";
