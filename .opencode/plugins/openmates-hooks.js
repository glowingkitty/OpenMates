// OpenMates OpenCode hook bridge.
//
// Keep interactive edits fast. Durable checks belong at test and deploy time;
// hooks only prevent unambiguous unsafe operations and preserve compatibility
// with the small set of canonical Claude guards.

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";

const EDIT_TOOLS = new Set(["apply_patch", "edit", "write", "Edit", "Write"]);
const READ_TOOLS = new Set(["read", "Read"]);
const BASH_TOOLS = new Set(["bash", "Bash"]);
const TASK_TOOLS = new Set(["task", "Task"]);
const PROJECT_ROOT = "/home/superdev/projects/OpenMates";
const WORKTREE_ROOTS = [
  `${PROJECT_ROOT}/.openmates-agent-worktrees`,
  `${PROJECT_ROOT}/.agent-worktrees`,
  "/home/superdev/projects/.openmates-agent-worktrees",
];
const BRIDGE = `${PROJECT_ROOT}/.codex/hooks/claude-hook-bridge.sh`;
const SESSIONS_FILE = `${PROJECT_ROOT}/.claude/sessions.json`;
const REPO_RELATIVE_PREFIXES = ["frontend/", "backend/", "scripts/", "docs/", "apple/", ".opencode/", ".claude/"];
const SOURCE_FILE_EXTENSION = /\.(?:py|js|mjs|ts|tsx|svelte|swift|md|ya?ml|json)$/;
const CLI_LOGIN_HINT_MARKER = "[OpenMates CLI login hint]";
const COMMAND_DOCTOR_MARKER = "[OpenMates command doctor]";
const FAILED_TEST_LEASE_MARKER = "[OpenMates failed-test lease hint]";
const NATIVE_HANDOFF_MARKER = "[OpenMates native worktree handoff]";
const ROOT_GUARD_MARKER = "[OpenMates worktree guard]";
const DOCKER_LOCK_MARKER = "[OpenMates Docker lock guard]";
const DOCKER_COMPOSE_MUTATIONS = new Set(["build", "down", "kill", "restart", "rm", "start", "stop", "up"]);
const COMPOSE_OPTIONS_WITH_VALUES = new Set(["-f", "--file", "--env-file", "-p", "--project-name", "--profile", "--project-directory"]);
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

function sessionsData() {
  try {
    return JSON.parse(readFileSync(SESSIONS_FILE, "utf8"));
  } catch {
    return {};
  }
}

function activeSessionRecord(sessionID, data = sessionsData()) {
  if (!sessionID) return null;
  for (const [id, session] of Object.entries(data.sessions || {})) {
    if (session?.opencode_session_id === sessionID) return { id, session, data };
  }
  return null;
}

function activeWorktreePath(sessionID) {
  const record = activeSessionRecord(sessionID);
  const worktree = record?.session?.worktree;
  if (worktree?.status === "active" && typeof worktree.path === "string") return worktree.path;
  return "";
}

export function nativeBindingDecisionForTest({ session = {}, currentDirectory = "", strict = false } = {}) {
  const worktreePath = session?.worktree?.status === "active" ? session.worktree.path || "" : "";
  const mode = session?.binding_mode || "legacy_grandfathered";
  if (mode === "native" && worktreePath && resolve(currentDirectory) === resolve(worktreePath)) {
    return { decision: "native", rewrite: false, block: false, worktreePath };
  }
  if (mode === "pilot_fallback" && !strict) {
    return {
      decision: "pilot_fallback",
      rewrite: true,
      block: false,
      worktreePath,
      reason: session.binding_failure_reason || "native_binding_failed",
    };
  }
  if (mode === "pending" || mode === "native" || (mode === "pilot_fallback" && strict)) {
    return {
      decision: "blocked",
      rewrite: false,
      block: true,
      worktreePath,
      reason: "Native binding is required before source edits",
    };
  }
  return { decision: "legacy_grandfathered", rewrite: true, block: false, worktreePath };
}

async function sessionDirectory(client, sessionID, directory = "") {
  if (!client?.session?.get || !sessionID) return "";
  try {
    const result = await client.session.get(directory ? { sessionID, directory } : { sessionID });
    return result?.data?.directory || result?.directory || "";
  } catch {
    return "";
  }
}

async function nativeBindingDecision(sessionID, currentDirectory) {
  const record = activeSessionRecord(sessionID);
  if (!record) return nativeBindingDecisionForTest();
  const decision = nativeBindingDecisionForTest({
    session: record.session,
    currentDirectory,
    strict: String(process.env.OPENMATES_NATIVE_WORKTREE_MODE || "pilot").toLowerCase() === "strict",
  });
  if (decision.block && record.session?.binding_mode === "native" && decision.worktreePath) {
    decision.reason = `This chat has moved to its native worktree. Continue the same chat here: ${nativeSessionUrlForTest(sessionID, decision.worktreePath)}`;
  }
  return decision;
}

export function nativeSessionUrlForTest(sessionID, directory, baseURL = "") {
  const token = Buffer.from(resolve(directory), "utf8").toString("base64url");
  return `${baseURL.replace(/\/$/, "")}/${token}/session/${sessionID}`;
}

export function taskRootDecisionForTest({ currentDirectory = PROJECT_ROOT, session = null } = {}) {
  if (!pathInProjectRoot(currentDirectory) || pathInWorktree(currentDirectory)) return { decision: "allow" };
  if (session?.mode === "question" && session?.binding_mode === "legacy_grandfathered") return { decision: "allow" };
  const worktreePath = session?.worktree?.path || "";
  return {
    decision: "block",
    reason: worktreePath
      ? `Open the native worktree chat before launching a child: ${worktreePath}`
      : "Initialize the repository session before launching a child: python3 scripts/sessions.py start --mode <mode> --task \"...\"",
  };
}

function recordNativeBinding(sessionID, mode, directory = "", reason = "") {
  const args = ["scripts/sessions.py", "worktree", "binding", "--opencode-session", sessionID, "--mode", mode];
  if (directory) args.push("--directory", directory);
  if (reason) args.push("--reason", reason);
  const result = spawnSync("python3", args, { cwd: PROJECT_ROOT, encoding: "utf8" });
  if (result.status !== 0) throw new Error((result.stderr || result.stdout || "Failed to record native binding").trim());
}

async function bindNativeWorktree(client, sessionID) {
  const record = activeSessionRecord(sessionID);
  const worktreePath = record?.session?.worktree?.path;
  if (!client || !record || !worktreePath || record.session.binding_mode !== "pending") return null;
  if (record.session?.worktree?.bootstrap?.status !== "ready") {
    recordNativeBinding(sessionID, "pilot_fallback", "", "worktree_bootstrap_failed");
    return { fallbackReason: "worktree_bootstrap_failed" };
  }
  try {
    const move = client?.experimental?.controlPlane?.moveSession;
    if (typeof move !== "function") throw new Error("move_session_unavailable");
    await move(
      { sessionID, destination: { directory: worktreePath }, moveChanges: false },
      { throwOnError: true },
    );
    const movedDirectory = await sessionDirectory(client, sessionID, worktreePath);
    if (!movedDirectory || resolve(movedDirectory) !== resolve(worktreePath)) {
      throw new Error("move_session_directory_mismatch");
    }
    recordNativeBinding(sessionID, "native", worktreePath);
    return {
      worktreePath,
      url: nativeSessionUrlForTest(sessionID, worktreePath),
    };
  } catch (error) {
    const reason = error instanceof Error && error.message ? error.message.slice(0, 160) : "native_binding_failed";
    recordNativeBinding(sessionID, "pilot_fallback", "", reason);
    return { fallbackReason: reason };
  }
}

function appendNativeHandoff(output, handoff) {
  if (!handoff || !output || typeof output.output !== "string" || output.output.includes(NATIVE_HANDOFF_MARKER)) return;
  if (handoff.fallbackReason) {
    output.output += `

${NATIVE_HANDOFF_MARKER}
Native movement was unavailable; visible pilot fallback is active.
Reason: ${handoff.fallbackReason}`;
    return;
  }
  if (!handoff.url) return;
  output.output += `

${NATIVE_HANDOFF_MARKER}
The isolated workspace is ready. Stop using repository tools in this turn.
Continue this same chat in its native worktree: ${handoff.url}
After opening the link, continue the original task from the existing conversation.`;
}

function pathInProjectRoot(file) {
  if (!file) return false;
  const relativePath = relative(resolve(PROJECT_ROOT), resolve(file));
  return relativePath === "" || (relativePath !== ".." && !relativePath.startsWith(`..${sep}`) && !isAbsolute(relativePath));
}

function pathInWorktree(file) {
  if (!file || !isAbsolute(file)) return false;
  const resolvedFile = resolve(file);
  return WORKTREE_ROOTS.some((root) => {
    const relativePath = relative(resolve(root), resolvedFile);
    return relativePath !== "" && relativePath !== ".." && !relativePath.startsWith(`..${sep}`) && !isAbsolute(relativePath);
  });
}

function rewritePathForWorktree(file, worktreePath) {
  if (!worktreePath || !file || pathInWorktree(file)) return file;
  if (isAbsolute(file) && pathInProjectRoot(file)) {
    const relativePath = relative(resolve(PROJECT_ROOT), resolve(file));
    return relativePath ? `${worktreePath}/${relativePath}` : worktreePath;
  }
  if (isAbsolute(file)) return file;
  const resolvedWorktree = resolve(worktreePath);
  const resolvedTarget = resolve(resolvedWorktree, file);
  const worktreeRelative = relative(resolvedWorktree, resolvedTarget);
  if (worktreeRelative === ".." || worktreeRelative.startsWith(`..${sep}`) || isAbsolute(worktreeRelative)) return file;
  return worktreeRelative ? `${worktreePath}/${worktreeRelative}` : worktreePath;
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

function composeActionFromArgs(args, startIndex) {
  let index = startIndex;
  while (index < args.length) {
    const arg = args[index];
    if (arg === "--") {
      index += 1;
      continue;
    }
    if (isOption(arg)) {
      index = skipOption(args, index, COMPOSE_OPTIONS_WITH_VALUES);
      continue;
    }
    return basename(arg);
  }
  return "";
}

function dockerComposeMutation(command) {
  for (const tokens of commandSegmentTokens(command.replace(/\\\s*\n/g, " "))) {
    const invocation = normalizedInvocation(tokens);
    const { command: commandName, args } = invocation;
    if (commandName === "docker-compose") {
      if (DOCKER_COMPOSE_MUTATIONS.has(composeActionFromArgs(args, 0))) return true;
      continue;
    }
    if (commandName !== "docker") continue;
    const composeIndex = args.findIndex((arg) => basename(arg) === "compose");
    if (composeIndex === -1) continue;
    if (DOCKER_COMPOSE_MUTATIONS.has(composeActionFromArgs(args, composeIndex + 1))) return true;
  }
  return false;
}

function sessionHasDockerLock(sessionID, data = sessionsData()) {
  const record = activeSessionRecord(sessionID, data);
  const shortID = record?.id || sessionID || "";
  const lock = data?.locks?.docker_rebuild || {};
  return lock.status === "IN_PROGRESS" && lock.claimed_by === shortID;
}

export function dockerMutationDecisionForTest({ command = "", sessionID = "", data = null } = {}) {
  if (!dockerComposeMutation(command)) return { decision: "allow", message: "not a Docker Compose mutation" };
  if (sessionHasDockerLock(sessionID, data || sessionsData())) return { decision: "allow", message: "Docker lock held by this session" };
  const record = activeSessionRecord(sessionID, data || sessionsData());
  const shortID = record?.id || "<id>";
  return {
    decision: "block",
    message: `${DOCKER_LOCK_MARKER} Docker Compose mutations require the sessions.py Docker lock. Run: python3 scripts/sessions.py lock --session ${shortID} --type docker; release immediately after with: python3 scripts/sessions.py unlock --session ${shortID} --type docker`,
  };
}

function guardDockerMutation(command, sessionID) {
  const decision = dockerMutationDecisionForTest({ command, sessionID });
  if (decision.decision === "block") throw new Error(decision.message);
}

function guardBash(command, sessionID) {
  guardForbiddenLocalTests(command);
  guardDockerMutation(command, sessionID);
  const repositoryMutation = /\bgit\s+apply\b/.test(command);
  const writesRepositoryFile = extractWriteTargets(command).some(isRepositoryWritePath);
  if (repositoryMutation || writesRepositoryFile) {
    throw new Error("Use apply_patch for source-file changes so edits remain reviewable.");
  }
}

function guardForbiddenLocalTests(command) {
  for (const tokens of commandSegmentTokens(command.replace(/\\\s*\n/g, " "))) {
    const invocation = normalizedInvocation(tokens);
    if (!invocation.command) continue;
    const { command: commandName, args } = invocation;
    const firstArg = firstNonOption(args);
    const secondArg = firstNonOption(args.slice(args.indexOf(firstArg) + 1));

    if (commandName === "vitest") {
      throw new Error("Use python3 scripts/tests.py run --suite vitest instead of local Vitest.");
    }
    if (commandName === "playwright" && firstArg === "test") {
      throw new Error("Use python3 scripts/tests.py run --spec <name>.spec.ts or --suite playwright instead of local Playwright.");
    }
    if (commandName === "pnpm" && ["test", "vitest"].includes(firstArg)) {
      throw new Error("Use python3 scripts/tests.py run --suite vitest instead of local Vitest/pnpm test.");
    }
    if (commandName === "pnpm" && firstArg === "playwright" && secondArg === "test") {
      throw new Error("Use python3 scripts/tests.py run --spec <name>.spec.ts or --suite playwright instead of local Playwright.");
    }
    if (commandName === "npx" && firstArg === "vitest") {
      throw new Error("Use python3 scripts/tests.py run --suite vitest instead of local Vitest.");
    }
    if (commandName === "npx" && firstArg === "playwright" && secondArg === "test") {
      throw new Error("Use python3 scripts/tests.py run --spec <name>.spec.ts or --suite playwright instead of local Playwright.");
    }
  }
}

function commandSegmentTokens(command) {
  const segments = [];
  let current = [];
  for (const token of tokenizeCommand(command)) {
    if (isSeparator(token)) {
      if (current.length) segments.push(current);
      current = [];
      continue;
    }
    current.push(token);
  }
  if (current.length) segments.push(current);
  return segments;
}

function commandSegments(command) {
  return commandSegmentTokens(command).map((segment) => segment.join(" "));
}

function isAssignment(token) {
  return /^[A-Za-z_][A-Za-z0-9_]*=/.test(token);
}

function firstNonOption(args) {
  for (const arg of args || []) {
    if (arg === "--") continue;
    if (!isOption(arg)) return basename(arg);
  }
  return "";
}

function normalizedInvocation(tokens) {
  let index = 0;
  while (index < tokens.length && isAssignment(tokens[index])) index += 1;
  if (index >= tokens.length) return { command: "", args: [] };

  let commandName = basename(tokens[index]);
  let args = tokens.slice(index + 1);
  if (["command", "builtin"].includes(commandName) && args.length) {
    commandName = basename(args[0]);
    args = args.slice(1);
  }
  if (commandName === "env") {
    let envIndex = 0;
    while (envIndex < args.length) {
      if (args[envIndex] === "--") {
        envIndex += 1;
        break;
      }
      if (isAssignment(args[envIndex])) {
        envIndex += 1;
        continue;
      }
      if (isOption(args[envIndex])) {
        envIndex = skipOption(args, envIndex, new Set(["-u", "--unset", "-C", "--chdir", "-S", "--split-string"]));
        continue;
      }
      break;
    }
    if (envIndex < args.length) return { command: basename(args[envIndex]), args: args.slice(envIndex + 1) };
  }
  if (commandName === "timeout" && args.length) {
    let timeoutIndex = 0;
    while (timeoutIndex < args.length && isOption(args[timeoutIndex])) {
      timeoutIndex = skipOption(args, timeoutIndex, new Set(["-k", "--kill-after", "-s", "--signal"]));
    }
    if (timeoutIndex < args.length) timeoutIndex += 1;
    if (timeoutIndex < args.length) return { command: basename(args[timeoutIndex]), args: args.slice(timeoutIndex + 1) };
  }
  return { command: commandName, args };
}

function skipOption(args, index, optionsWithValues) {
  const arg = args[index];
  if (optionsWithValues.has(arg)) return Math.min(index + 2, args.length);
  for (const option of optionsWithValues) {
    if (option.startsWith("--") && arg.startsWith(`${option}=`)) return index + 1;
  }
  return index + 1;
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

function runBridge(event, payload, sessionID, cwd = activeCwd()) {
  const result = spawnSync("bash", [BRIDGE, event], {
    cwd,
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

function bridgePayload(event, tool, args, cwd = activeCwd()) {
  return {
    cwd,
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
  return pathInWorktree(cwd) || pathInWorktree(target);
}

function worktreeGuardMessage(sessionID, worktreePath = "") {
  const target = worktreePath ? ` Edit in ${worktreePath} instead.` : "";
  return `${ROOT_GUARD_MARKER} Root checkout is the OpenMates control plane.${target} Use the session worktree for source edits: python3 scripts/sessions.py worktree ensure --session ${sessionID || "<id>"}`;
}

export function rootGuardDecisionForTest({ mode = "strict", cwd = PROJECT_ROOT, target = "", sessionID = "", opencodeSessionID = "", sessions = null, worktreePath = "" } = {}) {
  const normalized = String(mode || "strict").toLowerCase();
  if (["off", "0", "false"].includes(normalized)) return { decision: "allow", message: "root guard disabled" };
  if (!isInsideProjectRoot(target) || isInsideAgentWorktree(cwd, target)) return { decision: "allow", message: "target is not a root checkout source edit" };
  const mappedSessionID = opencodeSessionID ? activeSessionRecord(opencodeSessionID, sessions || sessionsData())?.id : "";
  const message = worktreeGuardMessage(sessionID || mappedSessionID, worktreePath);
  if (worktreePath) return { decision: "block", message };
  return { decision: normalized === "strict" ? "block" : "warn", message };
}

function guardRootEdit(files, sessionID, worktreePath = "") {
  const data = sessionsData();
  for (const file of files) {
    const decision = rootGuardDecisionForTest({
      mode: process.env.OPENMATES_ROOT_GUARD || "strict",
      cwd: process.cwd(),
      target: file,
      opencodeSessionID: sessionID,
      sessions: data,
      worktreePath,
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

export function editedFilesForBindingForTest(args, binding = {}) {
  return editedFilesForTest(args, binding.worktreePath || activeCwd());
}

function explicitFilesForTest(args, cwd = activeCwd()) {
  const input = toolInput(args);
  const explicit = input.file_path || input.filePath || input.path;
  return explicit ? [toAbsPath(explicit, cwd)] : [];
}

function runStaleRead(action, files, sessionID) {
  if (!sessionID) return;
  for (const file of files) {
    const result = spawnSync("python3", ["scripts/sessions.py", "stale-read", action, "--opencode-session", sessionID, "--file", file], {
      cwd: PROJECT_ROOT,
      encoding: "utf8",
    });
    const stdout = (result.stdout || "").trim();
    const stderr = (result.stderr || "").trim();
    if (stdout) console.log(stdout);
    if (stderr) console.error(stderr);
    if (result.status === 2) throw new Error(stderr || stdout || "OpenCode stale-read guard blocked edit");
  }
}

function runEditLease(action, files, sessionID) {
  if (!sessionID || !files.length) return;
  const result = spawnSync("python3", ["scripts/sessions.py", "edit-lease", action, "--opencode-session", sessionID, "--file", ...files], {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
  });
  const stdout = (result.stdout || "").trim();
  const stderr = (result.stderr || "").trim();
  if (stdout) console.log(stdout);
  if (stderr) console.error(stderr);
  if (result.status === 2) throw new Error(stderr || stdout || "OpenCode edit lease blocked edit");
  if (result.status !== 0) throw new Error(stderr || stdout || `OpenCode edit lease failed with exit ${result.status}`);
}

export const OpenMatesHooks = async ({ client, directory } = {}) => {
  const instanceDirectory = directory || activeCwd();
  return {
    "shell.env": async (input, output) => {
      if (!input?.sessionID) return;
      output.env ||= {};
      output.env.OPENCODE_SESSION_ID = input.sessionID;
    },
    "tool.execute.before": async (input, output) => {
      const tool = input.tool || "";
      if (!BASH_TOOLS.has(tool) && !EDIT_TOOLS.has(tool) && !READ_TOOLS.has(tool) && !TASK_TOOLS.has(tool)) return;

      const binding = await nativeBindingDecision(input.sessionID, instanceDirectory);
      if (binding.block) throw new Error(binding.reason);

      if (TASK_TOOLS.has(tool)) {
        const taskDecision = taskRootDecisionForTest({
          currentDirectory: instanceDirectory,
          session: activeSessionRecord(input.sessionID)?.session || null,
        });
        if (taskDecision.decision === "block") throw new Error(taskDecision.reason);
        return;
      }

      if (BASH_TOOLS.has(tool)) guardBash(bashCommand(output?.args || input?.args), input.sessionID);
      bindSessionStart(input, output);
      if (READ_TOOLS.has(tool)) {
        if (binding.rewrite && binding.worktreePath) output.args = rewriteEditArgsForTest(output?.args || input?.args, binding.worktreePath);
      }
      if (EDIT_TOOLS.has(tool)) {
        if (binding.rewrite && binding.worktreePath) output.args = rewriteEditArgsForTest(output?.args || input?.args, binding.worktreePath);
        const files = editedFilesForBindingForTest(output?.args || input?.args, binding);
        runStaleRead("check", files, input.sessionID);
        guardRootEdit(files, input.sessionID, binding.worktreePath);
        runBridge("PreToolUse", bridgePayload("PreToolUse", tool, output?.args, instanceDirectory), input.sessionID, instanceDirectory);
        runEditLease("acquire", files, input.sessionID);
        return;
      }
      runBridge("PreToolUse", bridgePayload("PreToolUse", tool, output?.args, instanceDirectory), input.sessionID, instanceDirectory);
    },
    "tool.execute.after": async (input, output) => {
      const tool = input.tool || "";
      if (BASH_TOOLS.has(tool)) {
        const command = bashCommand(toolArgs(input, output));
        if (isCliAuthFailure(command, output?.output || "")) appendCliLoginHint(output);
        appendCommandDoctorHint(command, output);
        appendFailedTestLeaseHint(command, output);
        if (/python3\s+scripts\/sessions\.py\s+start\b/.test(command)) {
          const handoff = await bindNativeWorktree(client, input.sessionID);
          appendNativeHandoff(output, handoff);
        }
      }
      if (READ_TOOLS.has(tool)) {
        const binding = await nativeBindingDecision(input.sessionID, instanceDirectory);
        runStaleRead("record", explicitFilesForTest(toolArgs(input, output), binding.worktreePath || activeCwd()), input.sessionID);
      }
      if (!EDIT_TOOLS.has(tool)) return;
      const binding = await nativeBindingDecision(input.sessionID, instanceDirectory);
      const files = editedFilesForBindingForTest(toolArgs(input, output), binding);
      try {
        runBridge("PostToolUse", bridgePayload("PostToolUse", tool, toolArgs(input, output), instanceDirectory), input.sessionID, instanceDirectory);
        runStaleRead("sync", files, input.sessionID);
      } finally {
        runEditLease("release", files, input.sessionID);
      }
    },
  };
};
