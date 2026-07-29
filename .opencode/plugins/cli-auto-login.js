// OpenMates OpenCode plugin: automatically refresh the local CLI dev-session
// after a CLI command emits the explicit login hint. This keeps agent-driven
// CLI verification from stopping at a known recoverable auth precondition.

import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const CLI_LOGIN_HINT = "[OpenMates CLI login hint]";
const LOGIN_SCRIPT = "scripts/openmates_cli_test_account.mjs";
const CLI_AUTH_ERROR_PATTERNS = [
  /Authentication failed\. Run [`']openmates login[`'] to re-authenticate\./i,
  /Session expired or invalid\. Please run [`']openmates login[`'] to re-authenticate\./i,
  /Session is invalid\. Please run [`']openmates login[`']\./i,
  /Not logged in\. Run [`']openmates login[`']\./i,
  /Ensure you are logged in \(run [`']openmates login[`']\)\./i,
  /Email encryption key is missing\. Run [`']openmates login[`'] again/i,
  /Requires login \(run [`']openmates login[`'] first\)\./i,
];

function bashCommand(args) {
  if (typeof args === "string") return args;
  if (!args || typeof args !== "object") return "";
  return args.command || args.cmd || args.script || "";
}

function commandRunsOpenMatesCli(command) {
  return (
    /(^|\s)(npx\s+)?openmates(\s|$)/.test(command)
    || /frontend\/packages\/openmates-cli\/(dist\/)?cli\.js/.test(command)
    || /(^|\s)node\s+(\.\/)?(dist\/)?cli\.js(\s|$)/.test(command)
  );
}

export function shouldAutoLoginForTest(input, output) {
  if (input?.tool !== "bash") return false;
  if (typeof output?.output !== "string") return false;
  if (!output.output.includes(CLI_LOGIN_HINT)) return false;
  const command = bashCommand(output.args || input.args);
  if (!commandRunsOpenMatesCli(command)) return false;
  return CLI_AUTH_ERROR_PATTERNS.some((pattern) => pattern.test(output.output));
}

async function runCliAutoLogin(worktree) {
  const { stdout, stderr } = await execFileAsync(
    "node",
    [LOGIN_SCRIPT, "login"],
    {
      cwd: worktree,
      timeout: 120_000,
      env: process.env,
    },
  );

  return [stdout, stderr].filter(Boolean).join("\n").trim();
}

export async function server({ worktree }) {
  return {
    "tool.execute.after": async (input, output) => {
      if (!shouldAutoLoginForTest(input, output)) return;

      try {
        const loginOutput = await runCliAutoLogin(worktree);
        output.output += `\n\n[OpenMates CLI auto-login]\n${loginOutput || "Test account login completed."}`;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        output.output += `\n\n[OpenMates CLI auto-login failed]\n${message}`;
      }
    },
  };
}

export default server;
