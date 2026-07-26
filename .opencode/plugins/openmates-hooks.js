// OpenMates OpenCode hook bridge.
//
// Keep interactive edits fast. Durable checks belong at test and deploy time;
// hooks only prevent unambiguous unsafe operations and preserve compatibility
// with the small set of canonical Claude guards.

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";

const EDIT_TOOLS = new Set(["apply_patch", "edit", "write", "Edit", "Write"]);
const BASH_TOOLS = new Set(["bash", "Bash"]);
const PROJECT_ROOT = "/home/superdev/projects/OpenMates";
const BRIDGE = `${PROJECT_ROOT}/.codex/hooks/claude-hook-bridge.sh`;
const SESSIONS_FILE = `${PROJECT_ROOT}/.claude/sessions.json`;
const REPO_RELATIVE_PREFIXES = ["frontend/", "backend/", "scripts/", "docs/", "apple/", ".opencode/", ".claude/"];
const SOURCE_FILE_EXTENSION = /\.(?:py|js|mjs|ts|tsx|svelte|swift|md|ya?ml|json)$/;
const CLI_LOGIN_HINT_MARKER = "[OpenMates CLI login hint]";
const COMMAND_DOCTOR_MARKER = "[OpenMates command doctor]";
const FAILED_TEST_LEASE_MARKER = "[OpenMates failed-test lease hint]";
const ROOT_GUARD_MARKER = "[OpenMates worktree guard]";
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

function unquote(value) {
  if (!value) return "";
  const trimmed = value.trim().replace(/[),]+$/g, "");
  if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function tokenizeCommand(command) {
  const tokens = [];
  let token = "";
  let quote = "";

  for (let index = 0; index < command.length; index += 1) {
    const char = command[index];
    if (quote) {
      if (char === quote) quote = "";
      else token += char;
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }
    if (/\s/.test(char)) {
      if (token) tokens.push(token);
      token = "";
      continue;
    }
    if (";&|".includes(char)) {
      if (token) tokens.push(token);
      token = "";
      tokens.push(char);
      continue;
    }
    token += char;
  }

  if (token) tokens.push(token);
  return tokens;
}

function basename(commandToken) {
  return unquote(commandToken).split("/").pop() || "";
}

function isSeparator(token) {
  return token === ";" || token === "&" || token === "|";
}

function isOption(token) {
  return token.startsWith("-") && token !== "-";
}

function isRepositoryWritePath(candidate) {
  let file = unquote(candidate);
  if (!file || file === "-" || file.startsWith("$") || file.includes("://")) return false;
  if (file.startsWith(`${PROJECT_ROOT}/`) || file === PROJECT_ROOT) return true;
  if (file.startsWith("/")) return false;
  while (file.startsWith("./")) file = file.slice(2);
  if (file.startsWith("../")) return false;
  return REPO_RELATIVE_PREFIXES.some((prefix) => file.startsWith(prefix)) || SOURCE_FILE_EXTENSION.test(file);
}

function collectCommandArguments(tokens, startIndex) {
  const args = [];
  for (let index = startIndex + 1; index < tokens.length && !isSeparator(tokens[index]); index += 1) {
    args.push(tokens[index]);
  }
  return args;
}

function extractWriteTargets(command) {
  const targets = [];
  const redirectionPattern = /(?:^|[\s;&|])\d*(?:>>|>)(?![=>])\s*(?:"([^"]+)"|'([^']+)'|([^\s;&|]+))/g;
  let match;
  while ((match = redirectionPattern.exec(command)) !== null) targets.push(match[1] || match[2] || match[3]);

  const pathWritePattern = /\bPath\s*\(\s*(?:"([^"]+)"|'([^']+)')\s*\)\s*\.\s*write_(?:text|bytes)\s*\(/g;
  while ((match = pathWritePattern.exec(command)) !== null) targets.push(match[1] || match[2]);

  const openWritePattern = /\bopen\s*\(\s*(?:"([^"]+)"|'([^']+)')\s*,\s*(?:"[wa+x][^"]*"|'[wa+x][^']*')/g;
  while ((match = openWritePattern.exec(command)) !== null) targets.push(match[1] || match[2]);

  const nodeWritePattern = /\b(?:writeFile(?:Sync)?|appendFile(?:Sync)?)\s*\(\s*(?:"([^"]+)"|'([^']+)')/g;
  while ((match = nodeWritePattern.exec(command)) !== null) targets.push(match[1] || match[2]);

  const tokens = tokenizeCommand(command);
  for (let index = 0; index < tokens.length; index += 1) {
    const commandName = basename(tokens[index]);
    if (!commandName) continue;

    if (commandName === "patch") targets.push(PROJECT_ROOT);
    if (commandName === "dd") {
      for (const arg of collectCommandArguments(tokens, index)) {
        if (arg.startsWith("of=")) targets.push(arg.slice(3));
      }
    }
    if (["tee", "touch", "rm", "truncate"].includes(commandName)) {
      for (const arg of collectCommandArguments(tokens, index)) {
        if (!isOption(arg)) targets.push(arg);
      }
    }
    if (["cp", "mv", "install", "rsync"].includes(commandName)) {
      const args = collectCommandArguments(tokens, index).filter((arg) => !isOption(arg));
      if (args.length > 0) targets.push(args[args.length - 1]);
    }
    if ((commandName === "sed" || commandName === "perl") && collectCommandArguments(tokens, index).some((arg) => /^-.*i/.test(arg))) {
      for (const arg of collectCommandArguments(tokens, index)) {
        if (!isOption(arg)) targets.push(arg);
      }
    }
  }

  return targets;
}

function bindSessionStart(input, output) {
  const command = bashCommand(output?.args || input?.args);
  if (!input?.sessionID || !/python3\s+scripts\/sessions\.py\s+start\b/.test(command)) return;
  if (/--opencode-session\b/.test(command) || /[;&|]/.test(command)) return;
  output.args.command = `${command} --opencode-session ${input.sessionID}`;
}

function activeWorktreePath(sessionID) {
  if (!sessionID) return "";
  try {
    const data = JSON.parse(readFileSync(SESSIONS_FILE, "utf8"));
    for (const session of Object.values(data.sessions || {})) {
      if (session?.opencode_session_id !== sessionID) continue;
      const worktree = session?.worktree;
      if (worktree?.status === "active" && typeof worktree.path === "string") return worktree.path;
    }
  } catch {
    return "";
  }
  return "";
}

function pathInProjectRoot(file) {
  return file === PROJECT_ROOT || file?.startsWith(`${PROJECT_ROOT}/`);
}

function pathInWorktree(file) {
  return file?.includes("/.openmates-agent-worktrees/") || file?.includes("/.agent-worktrees/");
}

function shouldRewriteEditPath(file) {
  return Boolean(file) && !file.startsWith("/") && !file.startsWith("../") && !pathInWorktree(file);
}

function rewritePathForWorktree(file, worktreePath) {
  if (!worktreePath || !shouldRewriteEditPath(file)) return file;
  let relative = file;
  while (relative.startsWith("./")) relative = relative.slice(2);
  return `${worktreePath}/${relative}`;
}

function rewritePatchHeadersForWorktree(patchText, worktreePath) {
  if (!worktreePath || typeof patchText !== "string") return patchText;
  return patchText
    .split("\n")
    .map((line) => {
      for (const prefix of ["*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: "]) {
        if (!line.startsWith(prefix)) continue;
        const file = line.slice(prefix.length).trim();
        return `${prefix}${rewritePathForWorktree(file, worktreePath)}`;
      }
      return line;
    })
    .join("\n");
}

export function rewriteEditArgsForTest(args, worktreePath) {
  const input = toolInput(args);
  if (!worktreePath || !input || typeof input !== "object") return input;
  const rewritten = { ...input };
  for (const key of ["file_path", "filePath", "path"]) {
    if (typeof rewritten[key] === "string") rewritten[key] = rewritePathForWorktree(rewritten[key], worktreePath);
  }
  if (typeof rewritten.patchText === "string") rewritten.patchText = rewritePatchHeadersForWorktree(rewritten.patchText, worktreePath);
  if (typeof rewritten.patch === "string") rewritten.patch = rewritePatchHeadersForWorktree(rewritten.patch, worktreePath);
  return rewritten;
}

function guardBash(command) {
  guardForbiddenLocalTests(command);
  const repositoryMutation = /\bgit\s+apply\b/.test(command);
  const writesRepositoryFile = extractWriteTargets(command).some(isRepositoryWritePath);
  if (repositoryMutation || writesRepositoryFile) {
    throw new Error("Use apply_patch for source-file changes so edits remain reviewable.");
  }
}

function guardForbiddenLocalTests(command) {
  const normalized = command.replace(/\\\s*\n/g, " ");
  for (const segment of commandSegments(normalized)) {
    if (/scripts\/tests\.py\s+run\b/.test(segment)) continue;
    if (/\b(?:npx\s+)?vitest\b/.test(segment) || /\bpnpm\s+(?:test|vitest)\b/.test(segment)) {
      throw new Error("Use python3 scripts/tests.py run --suite vitest instead of local Vitest/pnpm test.");
    }
    if (/\b(?:npx\s+)?playwright\s+test\b/.test(segment) || /\bpnpm\s+playwright\s+test\b/.test(segment)) {
      throw new Error("Use python3 scripts/tests.py run --spec <name>.spec.ts or --suite playwright instead of local Playwright.");
    }
  }
}

function commandSegments(command) {
  const segments = [];
  let current = [];
  for (const token of tokenizeCommand(command)) {
    if (isSeparator(token)) {
      if (current.length) segments.push(current.join(" "));
      current = [];
      continue;
    }
    current.push(token);
  }
  if (current.length) segments.push(current.join(" "));
  return segments;
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

function appendCommandDoctorHint(command, output) {
  if (!output || typeof output.output !== "string" || output.output.includes(COMMAND_DOCTOR_MARKER)) return;
  const text = output.output;
  const suggestions = [];
  if (/usage: tests\.py[\s\S]*unrecognized arguments: --(?:suite|spec)\b/.test(text)) {
    suggestions.push("Run test dispatch through the current control-plane form: python3 scripts/tests.py run --suite <suite> or python3 scripts/tests.py run --spec <name>.spec.ts. For deployed UI evidence, add --gate-deploy --expected-commit <sha>.");
  }
  if (/usage: sessions\.py[\s\S]*unrecognized arguments: --session\b/.test(text) && /scripts\/sessions\.py\s+status\b/.test(command)) {
    suggestions.push("sessions.py status does not take --session in older checkouts. Use python3 scripts/sessions.py status, or python3 scripts/sessions.py summary --session <id> for one session.");
  }
  if (/scripts\/tests\.py\s+run\b/.test(command) && /(?:failed|timeout|timed out|result_unknown|dispatch_error)/i.test(text)) {
    suggestions.push("If this is daily-failure debugging, claim a failure lease before editing: python3 scripts/tests.py next --lease --session ${OPENCODE_SESSION_ID:-manual}. Then rerun with --lease-required --lease-id <lease>.");
  }
  if (!suggestions.length) return;
  output.output += `

${COMMAND_DOCTOR_MARKER}
${suggestions.map((suggestion) => `- ${suggestion}`).join("\n")}`;
}

function appendFailedTestLeaseHint(command, output) {
  if (!output || typeof output.output !== "string" || output.output.includes(FAILED_TEST_LEASE_MARKER)) return;
  if (!/scripts\/tests\.py\s+(?:triage|failed|next)\b/.test(command)) return;
  if (!/(Failures: [1-9]|\[playwright\]|\.spec\.ts|failed|timeout)/i.test(output.output)) return;
  output.output += `

${FAILED_TEST_LEASE_MARKER}
Parallel failed-test work should be leased before edits:
  python3 scripts/tests.py next --lease --session \${OPENCODE_SESSION_ID:-manual}
Use --lease-required --lease-id <lease> on follow-up test runs when debugging that group.`;
}

function activeCwd() {
  return process.cwd() || PROJECT_ROOT;
}

function runBridge(event, payload, sessionID) {
  const result = spawnSync("bash", [BRIDGE, event], {
    cwd: activeCwd(),
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
    cwd: activeCwd(),
    hook_event_name: event,
    tool_name: normalizeToolName(tool),
    tool_input: toolInput(args),
  };
}

function toAbsPath(file, cwd = activeCwd()) {
  return file?.startsWith("/") ? file : `${cwd}/${file || ""}`;
}

function isInsideProjectRoot(file) {
  const target = file || "";
  return pathInProjectRoot(target);
}

function isInsideAgentWorktree(cwd, target) {
  const combined = `${cwd || ""}\n${target || ""}`;
  return pathInWorktree(combined);
}

function worktreeGuardMessage(sessionID) {
  return `${ROOT_GUARD_MARKER} Root checkout is the OpenMates control plane. Use the session worktree for source edits: python3 scripts/sessions.py worktree ensure --session ${sessionID || "<id>"}`;
}

export function rootGuardDecisionForTest({ mode = "warn", cwd = PROJECT_ROOT, target = "", sessionID = "" } = {}) {
  const normalized = String(mode || "warn").toLowerCase();
  if (["off", "0", "false"].includes(normalized)) return { decision: "allow", message: "root guard disabled" };
  if (!isInsideProjectRoot(target) || isInsideAgentWorktree(cwd, target)) return { decision: "allow", message: "target is not a root checkout source edit" };
  const message = worktreeGuardMessage(sessionID);
  return { decision: normalized === "strict" ? "block" : "warn", message };
}

function guardRootEdit(files, sessionID) {
  for (const file of files) {
    const decision = rootGuardDecisionForTest({
      mode: process.env.OPENMATES_ROOT_GUARD || "warn",
      cwd: process.cwd(),
      target: file,
      sessionID,
    });
    if (decision.decision === "block") throw new Error(decision.message);
    if (decision.decision === "warn") console.warn(decision.message);
  }
}

export function editedFilesForTest(args, cwd = activeCwd()) {
  const input = toolInput(args);
  const explicit = input.file_path || input.filePath || input.path;
  if (explicit) return [toAbsPath(explicit, cwd)];

  const files = new Set();
  for (const line of (input.patchText || input.patch || "").split("\n")) {
    for (const prefix of ["*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: "]) {
      if (line.startsWith(prefix)) files.add(toAbsPath(line.slice(prefix.length).trim(), cwd));
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
    if (EDIT_TOOLS.has(tool)) {
      const worktreePath = activeWorktreePath(input.sessionID);
      if (worktreePath) output.args = rewriteEditArgsForTest(output?.args || input?.args, worktreePath);
      guardRootEdit(editedFilesForTest(output?.args || input?.args), input.sessionID);
    }
    runBridge("PreToolUse", bridgePayload("PreToolUse", tool, output?.args), input.sessionID);
  },
  "tool.execute.after": async (input, output) => {
    const tool = input.tool || "";
    if (BASH_TOOLS.has(tool)) {
      const command = bashCommand(toolArgs(input, output));
      if (isCliAuthFailure(command, output?.output || "")) appendCliLoginHint(output);
      appendCommandDoctorHint(command, output);
      appendFailedTestLeaseHint(command, output);
    }
    if (!EDIT_TOOLS.has(tool)) return;
    runBridge("PostToolUse", bridgePayload("PostToolUse", tool, toolArgs(input, output)), input.sessionID);
  },
});
