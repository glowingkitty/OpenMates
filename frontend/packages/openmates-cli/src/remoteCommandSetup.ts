/** One-time, CLI-managed installation of the Linux remote-command boundary. */

import { spawn } from "node:child_process";
import { userInfo } from "node:os";
import { fileURLToPath } from "node:url";

import {
  inspectRemoteCommandCapability,
  type RemoteCommandCapability,
} from "./remoteCommandRuntime.js";

const SUDO = "/usr/bin/sudo";
const PYTHON = "/usr/bin/python3";

export const REMOTE_COMMAND_SETUP_REQUIRED = "remote_command_setup_required";

export class RemoteCommandSetupError extends Error {
  readonly code = REMOTE_COMMAND_SETUP_REQUIRED;

  constructor(message: string) {
    super(message);
    this.name = "RemoteCommandSetupError";
  }
}

export interface RemoteCommandSetupOptions {
  interactive: boolean;
  json: boolean;
}

export interface RemoteCommandSetupResult {
  installed: boolean;
  capability: RemoteCommandCapability;
}

interface InstallerResult {
  code: number | null;
  signal: NodeJS.Signals | null;
}

interface RemoteCommandSetupDependencies {
  inspectCapability?: () => RemoteCommandCapability;
  installerPath?: string;
  username?: string;
  uid?: number;
  runInstaller?: (executable: string, args: string[]) => Promise<InstallerResult>;
}

export function bundledRemoteCommandInstaller(moduleUrl = import.meta.url): string {
  return fileURLToPath(new URL("./remote-command-apparmor/setup_remote_command_apparmor.py", moduleUrl));
}

export async function ensureRemoteCommandSetup(
  options: RemoteCommandSetupOptions,
  dependencies: RemoteCommandSetupDependencies = {},
): Promise<RemoteCommandSetupResult> {
  const inspectCapability = dependencies.inspectCapability ?? inspectRemoteCommandCapability;
  const current = inspectCapability();
  if (current.supported) return { installed: false, capability: current };

  const reason = current.reason ? ` (${current.reason})` : "";
  if (options.json || !options.interactive) {
    throw new RemoteCommandSetupError(
      `Remote command protection needs one-time interactive operating-system setup${reason}. Rerun this command in an interactive terminal.`,
    );
  }

  const uid = dependencies.uid ?? process.getuid?.();
  const username = dependencies.username ?? userInfo().username;
  if (!Number.isSafeInteger(uid) || (uid as number) <= 0 || !username) {
    throw new RemoteCommandSetupError("Remote command setup must be started by a non-root local user.");
  }

  const installer = dependencies.installerPath ?? bundledRemoteCommandInstaller();
  const runInstaller = dependencies.runInstaller ?? inheritedInstaller;
  const result = await runInstaller(SUDO, ["--", PYTHON, installer, "--user", username]);
  if (result.code !== 0) {
    const outcome = result.signal ? `signal ${result.signal}` : `exit ${result.code ?? "unknown"}`;
    throw new RemoteCommandSetupError(`Remote command protection setup did not complete (${outcome}).`);
  }

  const installed = inspectCapability();
  if (!installed.supported) {
    const detail = installed.reason ? `: ${installed.reason}` : "";
    throw new RemoteCommandSetupError(`Remote command protection is still unavailable after setup${detail}`);
  }
  return { installed: true, capability: installed };
}

function inheritedInstaller(executable: string, args: string[]): Promise<InstallerResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { stdio: "inherit" });
    child.once("error", reject);
    child.once("close", (code, signal) => resolve({ code, signal }));
  });
}
