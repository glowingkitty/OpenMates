// OpenMates OpenCode hook bridge.
//
// Keeps OpenCode policy enforcement aligned with Claude/Codex without
// duplicating the individual hook scripts. Tool events are translated into the
// same payload shape consumed by the Codex Claude-hook bridge, which then runs
// the canonical hooks from `.claude/hooks/`.

import { spawnSync } from "node:child_process";

const EDIT_TOOLS = new Set(["apply_patch", "edit", "write", "Edit", "Write"]);
const BASH_TOOLS = new Set(["bash", "Bash"]);
const PROJECT_ROOT = "/home/superdev/projects/OpenMates";
const BRIDGE = `${PROJECT_ROOT}/.codex/hooks/claude-hook-bridge.sh`;
const POST_EDIT_LINTS = [
  `${PROJECT_ROOT}/scripts/lint-design-tokens.sh`,
  `${PROJECT_ROOT}/scripts/lint-swift-design-tokens.sh`,
];
const CLI_LOGIN_HINT_MARKER = "[OpenMates CLI login hint]";
const CLI_AUTH_ERROR_PATTERNS = [
  /Authentication failed\. Run [`']openmates login[`'] to re-authenticate\./i,
  /Session expired or invalid\. Please run [`']openmates login[`'] to re-authenticate\./i,
  /Session is invalid\. Please run [`']openmates login[`']\./i,
  /Not logged in\. Run [`']openmates login[`']\./i,
  /Ensure you are logged in \(run [`']openmates login[`']\)\./i,
  /Email encryption key is missing\. Run [`']openmates login[`'] again/i,
  /Requires login \(run [`']openmates login[`'] first\)\./i,
];

function normalizeToolName(tool) {
  if (tool === "edit") return "Edit";
  if (tool === "write") return "Write";
  return tool || "";
}

function toolInput(args) {
  if (!args || typeof args !== "object") return {};

  if (args.patch && !args.patchText) {
    return { ...args, patchText: args.patch };
  }

  return args;
}

function toolArgs(input, output) {
  return output?.args ?? input?.args ?? {};
}

function bashCommand(args) {
  if (typeof args === "string") return args;
  if (!args || typeof args !== "object") return "";
  return args.command || args.cmd || args.script || "";
}

function commandRunsOpenMatesCli(command) {
  return (
    /(^|\s)(npx\s+)?openmates(\s|$)/.test(command) ||
    /frontend\/packages\/openmates-cli\/(dist\/)?cli\.js/.test(command) ||
    /(^|\s)node\s+(\.\/)?(dist\/)?cli\.js(\s|$)/.test(command)
  );
}

function isCliAuthFailure(command, outputText) {
  const outputMentionsOpenMatesCli = /OpenMates CLI/i.test(outputText) || /openmates login/i.test(outputText);
  if (!commandRunsOpenMatesCli(command) && !outputMentionsOpenMatesCli) return false;
  return CLI_AUTH_ERROR_PATTERNS.some((pattern) => pattern.test(outputText));
}

function appendCliLoginHint(output) {
  if (!output || typeof output.output !== "string") return;
  if (output.output.includes(CLI_LOGIN_HINT_MARKER)) return;

  output.output += `

${CLI_LOGIN_HINT_MARKER}
The OpenMates CLI session is missing or invalid. Do not ask the user for test-account credentials.
Run this from the repo root to log the CLI into the dev test account automatically:
  node scripts/openmates_cli_test_account.mjs login
Then retry the OpenMates CLI command. The script reads OPENMATES_TEST_ACCOUNT_* values from .env/process.env and writes the normal ~/.openmates/session.json used by the CLI.`;
}

function runBridge(event, payload) {
  const result = spawnSync("bash", [BRIDGE, event], {
    cwd: PROJECT_ROOT,
    input: JSON.stringify(payload),
    encoding: "utf8",
  });

  const stdout = (result.stdout || "").trim();
  const stderr = (result.stderr || "").trim();

  if (stdout) console.log(stdout);
  if (stderr) console.error(stderr);

  if (result.status !== 0) {
    throw new Error(stderr || stdout || `OpenMates hook bridge failed with exit ${result.status}`);
  }
}

function runCommand(command, payload) {
  const result = spawnSync("bash", [command], {
    cwd: PROJECT_ROOT,
    input: JSON.stringify(payload),
    encoding: "utf8",
  });

  const stdout = (result.stdout || "").trim();
  const stderr = (result.stderr || "").trim();

  if (stdout) console.log(stdout);
  if (stderr) console.error(stderr);

  if (result.status !== 0 && result.status !== 2) {
    throw new Error(stderr || stdout || `OpenMates command hook failed with exit ${result.status}`);
  }
}

function bridgePayload(event, tool, args) {
  return {
    cwd: PROJECT_ROOT,
    hook_event_name: event,
    tool_name: normalizeToolName(tool),
    tool_input: toolInput(args),
  };
}

function toAbsPath(file) {
  if (!file) return "";
  return file.startsWith("/") ? file : `${PROJECT_ROOT}/${file}`;
}

function editedFiles(args) {
  const input = toolInput(args);
  const explicit = input.file_path || input.filePath || input.path;
  if (explicit) return [toAbsPath(explicit)];

  const patch = input.patchText || input.patch || "";
  const files = new Set();
  for (const line of patch.split("\n")) {
    for (const prefix of ["*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: "]) {
      if (line.startsWith(prefix)) {
        files.add(toAbsPath(line.slice(prefix.length).trim()));
      }
    }
  }
  return [...files].sort();
}

function filePayload(event, file) {
  return {
    cwd: PROJECT_ROOT,
    hook_event_name: event,
    tool_name: "Edit",
    tool_input: { file_path: file },
  };
}

export const OpenMatesHooks = async () => {
  return {
    "tool.execute.before": async (input, output) => {
      const tool = input.tool || "";
      if (!BASH_TOOLS.has(tool) && !EDIT_TOOLS.has(tool)) return;

      runBridge("PreToolUse", bridgePayload("PreToolUse", tool, output?.args));
    },
    "tool.execute.after": async (input, output) => {
      const tool = input.tool || "";
      if (BASH_TOOLS.has(tool)) {
        const command = bashCommand(toolArgs(input, output));
        if (isCliAuthFailure(command, output?.output || "")) {
          appendCliLoginHint(output);
        }
      }

      if (!EDIT_TOOLS.has(tool)) return;

      const args = toolArgs(input, output);
      runBridge("PostToolUse", bridgePayload("PostToolUse", tool, args));

      for (const file of editedFiles(args)) {
        const payload = filePayload("PostToolUse", file);
        for (const command of POST_EDIT_LINTS) {
          runCommand(command, payload);
        }
      }
    },
  };
};
