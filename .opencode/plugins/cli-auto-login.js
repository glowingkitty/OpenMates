// OpenMates OpenCode plugin: automatically refresh the local CLI dev-session
// after a CLI command emits the explicit login hint. This keeps agent-driven
// CLI verification from stopping at a known recoverable auth precondition.

import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const CLI_LOGIN_HINT = "[OpenMates CLI login hint]";
const LOGIN_SCRIPT = "scripts/openmates_cli_test_account.mjs";

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
      if (input.tool !== "bash") return;
      if (typeof output.output !== "string") return;
      if (!output.output.includes(CLI_LOGIN_HINT)) return;

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
