/**
 * Root `openmates` package export of `OpenMatesClient` for SDK integrations.
 *
 * The CLI imports its client from `./client.js` directly; only the public root
 * barrel uses this subclass. Implicitly loading the stored CLI login is
 * deprecated for SDK use (SDK credentials must be explicit). In 0.29.x it keeps
 * working and emits one `DeprecationWarning` (code OPENMATES_SDK_CLI_SESSION)
 * per process; pass `session` explicitly, `loadStoredSession: false`, or use
 * the `openmates/sdk/v1` SessionClient instead.
 */
import { OpenMatesClient as CliOpenMatesClient, type OpenMatesClientOptions } from "./client.js";

export const SDK_CLI_SESSION_DEPRECATION_CODE = "OPENMATES_SDK_CLI_SESSION";
let warned = false;

function warnImplicitCliSession(options: OpenMatesClientOptions): void {
  if (warned || options.session !== undefined || options.loadStoredSession === false) return;
  warned = true;
  process.emitWarning(
    "OpenMatesClient from the 'openmates' root export loads the stored CLI login implicitly. " +
      "This is deprecated: pass an explicit `session`, set `loadStoredSession: false`, or use " +
      "SessionClient from 'openmates/sdk/v1'. A future minor release will require explicit credentials.",
    { type: "DeprecationWarning", code: SDK_CLI_SESSION_DEPRECATION_CODE },
  );
}

export class OpenMatesClient extends CliOpenMatesClient {
  constructor(options: OpenMatesClientOptions = {}) {
    warnImplicitCliSession(options);
    super(options);
  }

  static override load(options: OpenMatesClientOptions = {}): OpenMatesClient {
    return new OpenMatesClient(options);
  }
}
