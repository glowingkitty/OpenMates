// OpenMates OpenCode hook bridge.
//
// Keep interactive edits fast. Durable checks belong at test and deploy time;
// hooks only prevent unambiguous unsafe operations and preserve compatibility
// with the small set of canonical Claude guards.

import { spawnSync } from "node:child_process";

const EDIT_TOOLS = new Set(["apply_patch", "edit", "write", "Edit", "Write"]);
const BASH_TOOLS = new Set(["bash", "Bash"]);
const PROJECT_ROOT = "/home/superdev/projects/OpenMates";
const BRIDGE = `${PROJECT_ROOT}/.codex/hooks/claude-hook-bridge.sh`;
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
  return args.patch && !args.patchText ? { ...args, patchText: args.patch } : args;
}

function toolArgs(input, output) {
  return output?.args ?? input?.args ?? {};
}

function bashCommand(args) {
  if (typeof args === "string") return args;
  if (!args || typeof args !== "object") return "";
  return args.command || args.cmd || args.script || "";
}

function bindSessionStart(input, output) {
  const command = bashCommand(output?.args || input?.args);
  if (!input?.sessionID || !/python3\s+scripts\/sessions\.py\s+start\b/.test(command)) return;
  if (/--opencode-session\b/.test(command) || /[;&|]/.test(command)) return;
  output.args.command = `${command} --opencode-session ${input.sessionID}`;
}

function guardBash(command) {
  const repositoryMutation = /\bgit\s+apply\b/.test(command);
  const directMutation = /\b(?:sed\s+-i|perl\s+-pi|tee|touch|cp|mv|rm|truncate|install|rsync|patch|dd)\b/.test(command)
    || /(?:^|[;&|])[^;&|]*(?:>>|>)(?![=>])/.test(command)
    || /\b(?:python3?|node)\b.*\b(?:open|write_text|write_bytes|writeFile(?:Sync)?|appendFile(?:Sync)?)\s*\(/.test(command);
  const repositorySource = /(?:^|[\s"'(])(?:frontend|backend|scripts|docs|apple|\.opencode|\.claude)\//.test(command)
    || /\.(?:py|js|mjs|ts|tsx|svelte|swift|md|ya?ml|json)(?:[\s"',)]|$)/.test(command);
  if (repositoryMutation || (directMutation && repositorySource)) {
    throw new Error("Use apply_patch for source-file changes so edits remain reviewable.");
  }
}

function commandRunsOpenMatesCli(command) {
  return (
    /(^|\s)(npx\s+)?openmates(\s|$)/.test(command)
    || /frontend\/packages\/openmates-cli\/(dist\/)?cli\.js/.test(command)
    || /(^|\s)node\s+(\.\/)?(dist\/)?cli\.js(\s|$)/.test(command)
  );
}

function isCliAuthFailure(command, outputText) {
  const outputMentionsOpenMatesCli = /OpenMates CLI/i.test(outputText) || /openmates login/i.test(outputText);
  if (!commandRunsOpenMatesCli(command) && !outputMentionsOpenMatesCli) return false;
  return CLI_AUTH_ERROR_PATTERNS.some((pattern) => pattern.test(outputText));
}

function appendCliLoginHint(output) {
  if (!output || typeof output.output !== "string" || output.output.includes(CLI_LOGIN_HINT_MARKER)) return;
  output.output += `

${CLI_LOGIN_HINT_MARKER}
The OpenMates CLI session is missing or invalid. Do not ask the user for test-account credentials.
Run this from the repo root to log the CLI into the dev test account automatically:
  node scripts/openmates_cli_test_account.mjs login`;
}

function runBridge(event, payload, sessionID) {
  const result = spawnSync("bash", [BRIDGE, event], {
    cwd: PROJECT_ROOT,
    env: sessionID ? { ...process.env, OPENCODE_SESSION_ID: sessionID } : process.env,
    input: JSON.stringify(payload),
    encoding: "utf8",
  });
  const stdout = (result.stdout || "").trim();
  const stderr = (result.stderr || "").trim();
  if (stdout) console.log(stdout);
  if (stderr) console.error(stderr);
  if (result.status !== 0) throw new Error(stderr || stdout || `OpenMates hook bridge failed with exit ${result.status}`);
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
  return file?.startsWith("/") ? file : `${PROJECT_ROOT}/${file || ""}`;
}

function editedFiles(args) {
  const input = toolInput(args);
  const explicit = input.file_path || input.filePath || input.path;
  if (explicit) return [toAbsPath(explicit)];

  const files = new Set();
  for (const line of (input.patchText || input.patch || "").split("\n")) {
    for (const prefix of ["*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: "]) {
      if (line.startsWith(prefix)) files.add(toAbsPath(line.slice(prefix.length).trim()));
    }
  }
  return [...files].sort();
}

export const OpenMatesHooks = async () => ({
  "shell.env": async (input, output) => {
    if (!input?.sessionID) return;
    output.env ||= {};
    output.env.OPENCODE_SESSION_ID = input.sessionID;
  },
  "tool.execute.before": async (input, output) => {
    const tool = input.tool || "";
    if (!BASH_TOOLS.has(tool) && !EDIT_TOOLS.has(tool)) return;

    if (BASH_TOOLS.has(tool)) guardBash(bashCommand(output?.args || input?.args));
    bindSessionStart(input, output);
    runBridge("PreToolUse", bridgePayload("PreToolUse", tool, output?.args), input.sessionID);
  },
  "tool.execute.after": async (input, output) => {
    const tool = input.tool || "";
    if (BASH_TOOLS.has(tool)) {
      const command = bashCommand(toolArgs(input, output));
      if (isCliAuthFailure(command, output?.output || "")) appendCliLoginHint(output);
    }
    if (!EDIT_TOOLS.has(tool)) return;
    runBridge("PostToolUse", bridgePayload("PostToolUse", tool, toolArgs(input, output)), input.sessionID);
  },
});
