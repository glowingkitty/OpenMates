/**
 * Root `openmates` package export of `OpenMatesClient` for SDK integrations.
 *
 * Since 0.30.0 the public SDK authenticates only with an explicit API key and is
 * fully separate from the CLI login: this class never reads the CLI state
 * directory, `session.json`, the OS keychain or any other CLI credential, and it
 * never falls back to anonymous use. It is the API-key `OpenMates` client with a
 * mandatory `apiKey`. The CLI imports its own session client from `./client.js`;
 * first-party harnesses that need the CLI login use the CLI-internal
 * `dist/cli-internal-client.js`, which is not an SDK entrypoint.
 */
import { OpenMates, OpenMatesConfigError, type OpenMatesOptions } from "./sdk.js";

export const SDK_API_KEY_REQUIRED_CODE = "OPENMATES_SDK_API_KEY_REQUIRED";

/** Raised when the root SDK client is constructed without an explicit API key. */
export class OpenMatesApiKeyRequiredError extends OpenMatesConfigError {
  readonly code = SDK_API_KEY_REQUIRED_CODE;
  constructor(message: string) {
    super(message);
    this.name = "OpenMatesApiKeyRequiredError";
  }
}

export interface OpenMatesClientOptions {
  /** API key created in Settings → Developers. Required; never read from the CLI login. */
  apiKey: string;
  apiUrl?: string;
  deviceId?: string;
  deviceIdPath?: string;
}

const ALLOWED_OPTIONS = new Set(["apiKey", "apiUrl", "deviceId", "deviceIdPath"]);
const MIGRATION =
  "Create an API key in Settings → Developers and pass it explicitly: new OpenMatesClient({ apiKey }). " +
  "The SDK never uses the CLI login.";

function requireApiKeyOptions(options: unknown): OpenMatesOptions {
  if (options === undefined || options === null || typeof options !== "object" || Array.isArray(options)) {
    throw new OpenMatesApiKeyRequiredError(`OpenMatesClient requires an explicit API key. ${MIGRATION}`);
  }
  const record = options as Record<string, unknown>;
  for (const key of Object.keys(record)) {
    if (key === "session" || key === "loadStoredSession") {
      throw new OpenMatesApiKeyRequiredError(`OpenMatesClient no longer accepts \`${key}\`; CLI sessions are not SDK credentials. ${MIGRATION}`);
    }
    if (!ALLOWED_OPTIONS.has(key)) throw new OpenMatesConfigError(`Unknown OpenMatesClient option: ${key}`);
  }
  if (typeof record.apiKey !== "string" || record.apiKey.trim() === "") {
    throw new OpenMatesApiKeyRequiredError(`OpenMatesClient requires an explicit API key. ${MIGRATION}`);
  }
  return { ...(record as unknown as OpenMatesClientOptions), anonymous: false, sdkName: "npm" };
}

export class OpenMatesClient extends OpenMates {
  constructor(options: OpenMatesClientOptions) {
    super(requireApiKeyOptions(options));
  }

  static load(options: OpenMatesClientOptions): OpenMatesClient {
    return new OpenMatesClient(options);
  }
}
