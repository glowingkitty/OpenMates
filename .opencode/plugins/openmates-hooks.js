// OpenMates OpenCode hook bridge.
//
// Keep interactive edits fast. Durable checks belong at test and deploy time;
// hooks only prevent unambiguous unsafe operations and preserve compatibility
// with the small set of canonical Claude guards.

import { spawn, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

let openCodeTool = null;
try {
  ({ tool: openCodeTool } = await import("@opencode-ai/plugin"));
} catch {
  // Node-only contract tests do not install the OpenCode plugin package. The
  // verified OpenCode runtime provides it when loading the live plugin.
}

const EDIT_TOOLS = new Set(["apply_patch", "edit", "write", "Edit", "Write"]);
const READ_TOOLS = new Set(["read", "Read"]);
const SEARCH_TOOLS = new Set(["glob", "grep", "Glob", "Grep"]);
const BASH_TOOLS = new Set(["bash", "Bash"]);
const TASK_TOOLS = new Set(["task", "Task"]);
const REVIEWER_SUBAGENTS = new Set(["code-reviewer"]);
const READ_ONLY_SUBAGENTS = new Set([
  "apple-native-debugger",
  "apple-parity-auditor",
  "apple-performance-detective",
  "chat-sync-detective",
  "e2e-test-investigator",
  "embed-rendering-investigator",
  "encryption-flow-tracer",
  "explore",
  "issue-forensics",
  "legal-compliance-auditor",
  "main-processor-guru",
  "seo-auditor",
  "settings-ui-consistency-checker",
  "skill-integration-doctor",
  "test-failure-triager",
]);
const WRITABLE_SUBAGENTS = new Set(["general"]);
const PROJECT_ROOT = process.env.OPENMATES_PROJECT_ROOT || "/home/superdev/projects/OpenMates";
const CONTROL_PLANE_RUNTIME = process.env.OPENMATES_CONTROL_PLANE_RUNTIME || "/home/superdev/projects/.openmates-runtime/opencode-server";
const CURRENT_CONTROL_PLANE_ROOT = existsSync(resolve(CONTROL_PLANE_RUNTIME, "scripts/sessions.py"))
  ? CONTROL_PLANE_RUNTIME
  : PROJECT_ROOT;
const WORKTREE_ROOTS = [
  `${PROJECT_ROOT}/.openmates-agent-worktrees`,
  `${PROJECT_ROOT}/.agent-worktrees`,
  "/home/superdev/projects/.openmates-agent-worktrees",
];
const BRIDGE = `${PROJECT_ROOT}/.codex/hooks/claude-hook-bridge.sh`;
const SESSIONS_FILE = `${PROJECT_ROOT}/.claude/sessions.json`;
const PRESENCE_FILE = `${PROJECT_ROOT}/.opencode/presence.json`;
const OPENCODE_NOTIFIER = `${PROJECT_ROOT}/scripts/opencode_progress_notifier.py`;
const OPENCODE_NOTIFIER_LOG = `${PROJECT_ROOT}/logs/opencode-event-notifier.log`;
const PRESENCE_DEBOUNCE_MS = 250;
const PRESENCE_HEARTBEAT_MS = 30_000;
const PRESENCE_READ_CACHE_MS = 1_000;
const PRESENCE_ABSENT_STATUS_GRACE_MS = 5_000;
const PRESENCE_LIVE_EXECUTION = new Set(["busy", "retrying"]);
const REPO_RELATIVE_PREFIXES = ["frontend/", "backend/", "scripts/", "docs/", "apple/", ".opencode/", ".claude/"];
const SOURCE_FILE_EXTENSION = /\.(?:py|js|mjs|ts|tsx|svelte|swift|md|ya?ml|json)$/;
const COMMAND_DOCTOR_MARKER = "[OpenMates command doctor]";
const FAILED_TEST_LEASE_MARKER = "[OpenMates failed-test lease hint]";
const TEMPORARY_LOCK_WAIT_MARKER = "[OpenMates temporary lock continuation]";
const OPAQUE_LONG_SLEEP_MARKER = "[OpenMates opaque long sleep guard]";
const API_HEALTH_WAIT_MARKER = "[OpenMates API health coordination]";
const RESPONSE_MEDIA_EMBED_MARKER = "[OpenMates response-media embed required]";
const FIGMA_REFERENCE_EMBED_MARKER = "[OpenMates Figma reference embed required]";
const CONTROL_PLANE_GUARD_MARKER = "[OpenMates control-plane guard]";
const GITHUB_MCP_GUARD_MARKER = "[OpenMates GitHub MCP guard]";
const ROUTING_GUARD_MARKER = "[OpenMates worktree routing]";
const ROOT_GUARD_MARKER = "[OpenMates worktree guard]";
const DOCKER_LIFECYCLE_MARKER = "[OpenMates server lifecycle guard]";
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
const HOOK_SOURCE_URL = new URL(import.meta.url);
const PROTECTED_CONTROL_PLANE_PATHS = [
  ".opencode/",
  "backend/engineering_control_plane/",
  "opencode.json",
  "scripts/opencode_credential_migration.py",
  "scripts/opencode_permission_watcher.py",
  "scripts/opencode_runtime_release.py",
  "scripts/sync_opencode_runtime_hook.py",
  "scripts/patches/opencode-",
  "scripts/server-restart.sh",
  "scripts/sessions.py",
  "scripts/start-opencode-server.sh",
];
const SECRET_CONFIG_PATHS = [
  "/home/superdev/.config/opencode/",
  "/home/superdev/opencode/.opencode/opencode.jsonc",
];
const SECRET_ENV_KEYS = [
  "BRAVE_API_KEY",
  "CONTEXT7_API_KEY",
  "FIRECRAWL_API_KEY",
  "GITHUB_PERSONAL_ACCESS_TOKEN",
  "PENPOT_ACCESS_TOKEN",
];
const HOOK_SUBPROCESS_TIMEOUT_MS = Number(process.env.OPENMATES_HOOK_SUBPROCESS_TIMEOUT_MS || 15_000);
const PRE_TOOL_HOOK_TIMEOUT_MS = Number(process.env.OPENMATES_PRE_TOOL_HOOK_TIMEOUT_MS || 45_000);
const TASK_CONTEXT_MARKER = "[OpenMates authoritative Task context]";

function hashHookSource() {
  try {
    return createHash("sha256").update(readFileSync(HOOK_SOURCE_URL)).digest("hex");
  } catch {
    return "unavailable";
  }
}

const HOOK_RUNTIME_HASH = hashHookSource();
const GITHUB_MCP_TOOL_PATTERN = /^(?:github|mcp__github)(?:[_\-.]|$)/i;
const HOOK_WARNING_DEDUPE_TTL_MS = Number(process.env.OPENMATES_HOOK_WARNING_DEDUPE_TTL_MS || 10 * 60 * 1000);
const hookWarningDedupe = new Map();

function actionable(marker, reason, next) {
  return `${marker} Reason: ${reason} Next: ${next}`;
}

async function withHookDeadlineForTest(label, sessionID, operation, timeoutMs = PRE_TOOL_HOOK_TIMEOUT_MS) {
  let timeout;
  try {
    return await Promise.race([
      Promise.resolve().then(operation),
      new Promise((_, reject) => {
        timeout = setTimeout(() => reject(new Error(actionable(
          "[OpenMates hook deadline]",
          `${label} did not settle within ${timeoutMs}ms for ${sessionID || "unknown session"}.`,
          "retry the tool once; if it repeats, the orchestration monitor must inspect the named hook stage rather than leaving the chat busy.",
        ))), timeoutMs);
      }),
    ]);
  } finally {
    if (timeout) clearTimeout(timeout);
  }
}

function warningReasonForTest(message) {
  const match = /Reason:\s*(.*?)(?:\s+Next:|$)/s.exec(String(message || ""));
  return (match?.[1] || String(message || "")).trim();
}

function warnOnceForTest(
  message,
  { sessionID = "", head = "", now = Date.now(), ttlMs = HOOK_WARNING_DEDUPE_TTL_MS } = {},
  warn = console.warn,
) {
  if (!message) return false;
  const ttl = Number.isFinite(Number(ttlMs)) ? Number(ttlMs) : HOOK_WARNING_DEDUPE_TTL_MS;
  if (ttl <= 0) {
    warn(message);
    return true;
  }
  const reason = warningReasonForTest(message);
  const key = JSON.stringify([HOOK_RUNTIME_HASH, sessionID || "", head || "", reason]);
  for (const [cachedKey, cachedAt] of hookWarningDedupe.entries()) {
    if (now - cachedAt > ttl) hookWarningDedupe.delete(cachedKey);
  }
  if (hookWarningDedupe.has(key)) return false;
  hookWarningDedupe.set(key, now);
  warn(message);
  return true;
}

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

function replaceToolArgs(output, current, routed) {
  if (!current || typeof current !== "object" || Array.isArray(current)) {
    output.args = routed;
    return routed;
  }
  for (const key of Object.keys(current)) delete current[key];
  Object.assign(current, routed);
  output.args = current;
  return current;
}

function bashCommand(args) {
  if (typeof args === "string") return args;
  if (!args || typeof args !== "object") return "";
  return args.command || args.cmd || args.script || "";
}

function firstUnquotedShellSeparatorIndex(command) {
  let quote = "";
  let escaped = false;
  for (let index = 0; index < command.length; index += 1) {
    const char = command[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (char === "\\" && quote !== "'") {
      escaped = true;
      continue;
    }
    if (quote) {
      if (char === quote) quote = "";
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      continue;
    }
    if (char === "\n" || ";&|".includes(char)) return index;
  }
  return -1;
}

function unquote(value) {
  if (!value) return "";
  const trimmed = value.trim().replace(/[),]+$/g, "");
  if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function shellUnescape(value) {
  return unquote(value).replace(/\\(.)/g, "$1");
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
    if (char === "\n") {
      if (token) tokens.push(token);
      token = "";
      tokens.push(";");
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

function hasUnsafeLocalShellExpansionOrRedirection(command) {
  let quote = "";
  let escaped = false;
  for (let index = 0; index < command.length; index += 1) {
    const char = command[index];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (char === "\\" && quote !== "'") {
      escaped = true;
      continue;
    }
    if (quote === "'") {
      if (char === "'") quote = "";
      continue;
    }
    if (quote === '"') {
      if (char === '"') quote = "";
      else if (char === "`" || (char === "$" && command[index + 1] === "(")) return true;
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      continue;
    }
    if (char === "`" || char === "<" || char === ">" || char === "\n") return true;
    if (char === "$" && command[index + 1] === "(") return true;
  }
  return quote !== "";
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
  const startCommand = command.trim();
  if (
    !/^python3\s+scripts\/sessions\.py\s+start\b/.test(startCommand)
    || firstUnquotedShellSeparatorIndex(startCommand) >= 0
  ) {
    throw new Error(actionable(
      ROUTING_GUARD_MARKER,
      "sessions.py start must be a standalone command so its OpenCode identity and worktree are created atomically.",
      "run python3 scripts/sessions.py start --mode <mode> --task \"brief description\" in its own tool call.",
    ));
  }
  if (/--opencode-session\b/.test(startCommand)) return;
  output.args.command = `${startCommand} --opencode-session ${input.sessionID}`;
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

function isoNow() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function attentionFromPending(state) {
  const questions = state.pending_question_ids.length > 0;
  const permissions = state.pending_permission_ids.length > 0;
  if (questions && permissions) return "required_both";
  if (questions) return "required_question";
  if (permissions) return "required_permission";
  return state.execution === "idle" ? "optional" : "none";
}

function initialPresenceForTest(sessionID, { questionCapability = "unsupported", childRole = "unknown" } = {}) {
  return {
    session_id: sessionID,
    top_level_session_id: sessionID,
    execution: "unknown",
    attention: "none",
    turn: "none",
    child_role: childRole,
    pending_permission_ids: [],
    pending_question_ids: [],
    capabilities: { question: questionCapability },
  };
}

function childRoleFromAgent(agent) {
  if (REVIEWER_SUBAGENTS.has(agent)) return "reviewer";
  if (READ_ONLY_SUBAGENTS.has(agent)) return "read_only";
  if (WRITABLE_SUBAGENTS.has(agent)) return "writable";
  return "unknown";
}

function hookRuntimeDiagnosticForTest(runtimeHash = HOOK_RUNTIME_HASH, sourceHash = hashHookSource()) {
  const validHash = (value) => /^[a-f0-9]{64}$/.test(value);
  return {
    runtimeHash,
    sourceHash,
    status: !validHash(runtimeHash) || !validHash(sourceHash)
      ? "unavailable"
      : (runtimeHash === sourceHash ? "current" : "stale_runtime"),
  };
}

function repeatedRoutingFailureMessageForTest(message, count, diagnostic = hookRuntimeDiagnosticForTest()) {
  if (count < 2) return message;
  const hashes = `hook runtime=${diagnostic.runtimeHash} source=${diagnostic.sourceHash} status=${diagnostic.status}`;
  const next = ["stale_runtime", "unavailable"].includes(diagnostic.status)
    ? "restart the OpenCode runtime once so it loads the current hook, then retry once."
    : "run python3 scripts/sessions.py status --json and return the routing diagnostics to the parent.";
  return `${message} Circuit breaker: Do not retry the same tool call. ${hashes}. Next: ${next}`;
}

function githubMcpGuardDecisionForTest(tool) {
  if (!GITHUB_MCP_TOOL_PATTERN.test(tool || "")) return { decision: "allow", message: "" };
  return {
    decision: "block",
    message: actionable(
      GITHUB_MCP_GUARD_MARKER,
      `GitHub MCP tool '${tool}' is not the canonical OpenMates GitHub access path and can use stale credentials.`,
      "use the authenticated local gh CLI from a sessions.py worktree, for example `gh pr list`, `gh run view`, or `gh api`.",
    ),
  };
}

function eventSessionID(event) {
  const properties = event?.properties || {};
  return properties.sessionID || properties.info?.sessionID || properties.info?.id || properties.part?.sessionID || "";
}

function withPending(state, field, id, add) {
  if (!id) return state;
  const values = new Set(state[field] || []);
  if (add) values.add(id);
  else values.delete(id);
  const next = { ...state, [field]: [...values].sort() };
  next.attention = attentionFromPending(next);
  return next;
}

function reducePresenceEventForTest(current, event, { now = isoNow() } = {}) {
  const sessionID = eventSessionID(event);
  if (!sessionID || sessionID !== current.session_id) return current;
  let state = { ...current, updated_at: now };
  const properties = event.properties || {};

  if (event.type === "session.status") {
    if (properties.status?.type === "busy") state = { ...state, execution: "busy", heartbeat_at: now };
    if (properties.status?.type === "retry") state = { ...state, execution: "retrying", heartbeat_at: now };
    if (properties.status?.type === "idle" && !["aborted", "failed"].includes(state.turn)) {
      state.execution = "idle";
    }
    state.attention = attentionFromPending(state);
    return state;
  }
  if (event.type === "session.idle") {
    if (!["aborted", "failed"].includes(state.turn)) state.execution = "idle";
    state.attention = attentionFromPending(state);
    return state;
  }
  if (event.type === "message.part.updated") {
    const messageID = properties.part?.messageID;
    if (!messageID) return state;
    return { ...state, execution: "busy", turn: "streaming", turn_id: messageID, attention: attentionFromPending({ ...state, execution: "busy" }), heartbeat_at: now };
  }
  if (event.type === "message.updated") {
    const info = properties.info || {};
    if (info.role === "user") {
      if (info.id && info.id === state.user_turn_id) return state;
      return { ...state, execution: "busy", turn: "none", turn_id: info.id, user_turn_id: info.id, attention: attentionFromPending({ ...state, execution: "busy" }), heartbeat_at: now };
    }
    if (info.role !== "assistant") return state;
    if (state.turn === "streaming" && state.turn_id && state.turn_id !== info.id) return state;
    const assistantState = { ...state, turn_id: info.id, user_turn_id: info.parentID || state.user_turn_id };
    if (info.error?.name === "MessageAbortedError") return { ...assistantState, execution: "stopped", turn: "aborted" };
    if (info.error) return { ...assistantState, execution: "error", turn: "failed" };
    if (info.time?.completed && info.finish === "unknown") return { ...assistantState, execution: "error", turn: "failed" };
    if (info.time?.completed) return { ...assistantState, turn: "completed" };
    return { ...assistantState, execution: "busy", turn: "streaming", heartbeat_at: now };
  }
  if (event.type === "permission.updated" || event.type === "permission.asked") {
    return withPending(state, "pending_permission_ids", properties.id, true);
  }
  if (event.type === "permission.replied") {
    return withPending(state, "pending_permission_ids", properties.permissionID || properties.requestID, false);
  }
  if (event.type === "question.asked" && state.capabilities?.question === "supported") {
    return withPending(state, "pending_question_ids", properties.id, true);
  }
  if (["question.replied", "question.rejected"].includes(event.type) && state.capabilities?.question === "supported") {
    return withPending(state, "pending_question_ids", properties.requestID, false);
  }
  if (event.type === "session.error") {
    if (properties.error?.name === "MessageAbortedError") return { ...state, execution: "stopped", turn: "aborted" };
    return { ...state, execution: "error", turn: "failed" };
  }
  if (event.type === "session.deleted") {
    return { ...state, execution: "closed", attention: "none", pending_permission_ids: [], pending_question_ids: [], paths: [] };
  }
  if (["session.created", "session.updated"].includes(event.type)) {
    const parentID = properties.info?.parentID;
    if (!parentID) return state;
    const explicitRole = childRoleFromAgent(properties.info?.agent || "");
    return {
      ...state,
      parent_id: parentID,
      top_level_session_id: parentID,
      child_role: explicitRole === "unknown" ? state.child_role : explicitRole,
    };
  }
  if (event.type === "openmates.child.role") {
    const role = properties.role;
    if (!["read_only", "reviewer", "writable"].includes(role)) return state;
    return { ...state, parent_id: properties.parentID, top_level_session_id: properties.parentID, child_role: role };
  }
  return state;
}

function createPresenceSchedulerForTest({
  persist,
  debounceMs = PRESENCE_DEBOUNCE_MS,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
} = {}) {
  const pending = new Map();
  let timer = null;
  let inFlight = false;

  const arm = () => {
    if (timer !== null || inFlight || pending.size === 0) return;
    timer = setTimer(flush, debounceMs);
    timer?.unref?.();
  };
  const flush = async () => {
    timer = null;
    if (inFlight || pending.size === 0) return;
    const records = [...pending.values()];
    pending.clear();
    inFlight = true;
    try {
      for (const record of records) await persist(record);
    } finally {
      inFlight = false;
      arm();
    }
  };
  return {
    schedule(record) {
      pending.set(record.session_id, record);
      arm();
    },
    pendingCount() {
      return pending.size;
    },
    async flush() {
      if (timer !== null) clearTimer(timer);
      timer = null;
      await flush();
    },
  };
}

function persistPresence(record) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn("python3", ["scripts/sessions.py", "presence", "update", "--json-stdin"], {
      cwd: CURRENT_CONTROL_PLANE_ROOT,
      env: process.env,
      stdio: ["pipe", "ignore", "pipe"],
    });
    let errorText = "";
    child.stderr.on("data", (chunk) => { errorText += chunk.toString(); });
    child.on("error", rejectPromise);
    child.on("close", (code) => {
      if (code === 0) resolvePromise();
      else rejectPromise(new Error(errorText.trim() || `presence writer exited ${code}`));
    });
    child.stdin.end(JSON.stringify(record));
  });
}

let presenceReadCache = { value: null, time: 0 };

function presenceData() {
  const now = Date.now();
  if (presenceReadCache.value && now - presenceReadCache.time < PRESENCE_READ_CACHE_MS) {
    return presenceReadCache.value;
  }
  try {
    const parsed = JSON.parse(readFileSync(PRESENCE_FILE, "utf8"));
    const value = parsed?.project_root === PROJECT_ROOT && parsed?.sessions
      ? parsed
      : { sessions: {}, task_claims: {}, child_roles: {} };
    presenceReadCache = { value, time: now };
    return value;
  } catch {
    const value = { sessions: {}, task_claims: {}, child_roles: {} };
    presenceReadCache = { value, time: now };
    return value;
  }
}

function collisionRelativePath(file, data) {
  if (!file) return "";
  const absolute = isAbsolute(file) ? resolve(file) : resolve(PROJECT_ROOT, file);
  for (const session of Object.values(data?.sessions || {})) {
    const worktree = session?.worktree?.path;
    if (!worktree) continue;
    const candidate = relative(resolve(worktree), absolute);
    if (candidate && candidate !== ".." && !candidate.startsWith(`..${sep}`) && !isAbsolute(candidate)) return candidate;
    const repoRoot = session?.repo_root;
    if (typeof repoRoot === "string" && repoRoot) {
      const repoCandidate = relative(resolve(repoRoot), absolute);
      if (repoCandidate && repoCandidate !== ".." && !repoCandidate.startsWith(`..${sep}`) && !isAbsolute(repoCandidate)) return repoCandidate;
    }
  }
  if (pathInProjectRoot(absolute)) return relative(PROJECT_ROOT, absolute);
  return isAbsolute(file) ? "" : file.replace(/^\.\//, "");
}

function relativePathWithinBase(file, basePath) {
  if (!file || !basePath) return "";
  const candidate = relative(resolve(basePath), resolve(file));
  if (!candidate || candidate === ".." || candidate.startsWith(`..${sep}`) || isAbsolute(candidate)) return "";
  return candidate;
}

function routedEditRelativePathForTest(file, worktreePath = "") {
  if (!file) return "";
  const absolute = isAbsolute(file) ? resolve(file) : resolve(worktreePath || PROJECT_ROOT, file);
  if (worktreePath) return relativePathWithinBase(absolute, worktreePath);
  if (pathInProjectRoot(absolute)) return relative(PROJECT_ROOT, absolute);
  return isAbsolute(file) ? "" : file.replace(/^\.\//, "");
}

function samePresenceWorkUnit(requesterID, ownerID, presence) {
  if (requesterID === ownerID) return true;
  const requester = presence?.sessions?.[requesterID] || {};
  const owner = presence?.sessions?.[ownerID] || {};
  const requesterTop = requester.top_level_session_id || requester.parent_id || requesterID;
  const ownerTop = owner.top_level_session_id || owner.parent_id || ownerID;
  return requesterTop === ownerTop && [requester.child_role, owner.child_role].some((role) => ["read_only", "reviewer"].includes(role));
}

function presenceRecordIsLive(record) {
  if (!PRESENCE_LIVE_EXECUTION.has(record?.execution)) return false;
  const timestamp = record.heartbeat_at || record.updated_at;
  if (!timestamp) return true;
  const age = Date.now() - Date.parse(timestamp);
  return Number.isFinite(age) && age >= -5_000 && age <= 120_000;
}

function readConflictWarningForTest({ path = "", sessionID = "", data = {}, presence = {} } = {}) {
  const relativePath = collisionRelativePath(path, data);
  const lease = data?.edit_leases?.[relativePath];
  if (!lease) return "";
  const ownerRecord = data?.sessions?.[lease.session_id];
  const ownerOpenCodeID = ownerRecord?.opencode_session_id || "";
  if (!ownerOpenCodeID || samePresenceWorkUnit(sessionID, ownerOpenCodeID, presence)) return "";
  if (!presenceRecordIsLive(presence?.sessions?.[ownerOpenCodeID])) return "";
  return `[OpenMates presence conflict] ${relativePath} currently has a live edit by repository session ${lease.session_id}. This read remains allowed; re-read after the lease releases before editing.`;
}

function routingDecisionForTest({ session = {}, pathExists = existsSync } = {}) {
  const repoRoot = typeof session?.repo_root === "string" ? session.repo_root : "";
  if (repoRoot && resolve(repoRoot) !== resolve(PROJECT_ROOT) && session?.mode !== "question") {
    return { decision: "worktree_routed", worktreePath: repoRoot, repoRoot, repoName: session.repo_name || "external" };
  }
  const worktreePath = ["active", "changes_pending", "merged"].includes(session?.worktree?.status) ? session.worktree.path || "" : "";
  if (
    worktreePath
    && isDirectManagedWorktree(worktreePath)
    && pathExists(worktreePath)
    && pathExists(resolve(worktreePath, ".git"))
  ) return { decision: "worktree_routed", worktreePath };
  if (session?.mode === "question") return { decision: "read_only", worktreePath: "" };
  return { decision: "unresolved", worktreePath: "" };
}

function isDirectManagedWorktree(candidate) {
  if (!candidate || !isAbsolute(candidate)) return false;
  const resolvedCandidate = resolve(candidate);
  return WORKTREE_ROOTS.some((root) => {
    const relativePath = relative(resolve(root), resolvedCandidate);
    return relativePath && !relativePath.includes(sep) && relativePath.startsWith("agent-");
  });
}

function canonicalPath(candidate) {
  const resolvedCandidate = resolve(candidate);
  let existing = resolvedCandidate;
  while (!existsSync(existing)) {
    const parent = dirname(existing);
    if (parent === existing) return resolvedCandidate;
    existing = parent;
  }
  try {
    return resolve(realpathSync.native(existing), relative(existing, resolvedCandidate));
  } catch {
    return resolvedCandidate;
  }
}

function pathEscapesWorktree(candidate, worktreePath) {
  const relativeTarget = relative(canonicalPath(worktreePath), canonicalPath(candidate));
  return relativeTarget === ".." || relativeTarget.startsWith(`..${sep}`) || isAbsolute(relativeTarget);
}

function targetsDifferentWorktree(candidate, worktreePath) {
  return isAbsolute(candidate) && pathInWorktree(candidate) && pathEscapesWorktree(candidate, worktreePath);
}

async function openCodeSession(client, sessionID) {
  if (!client?.session?.get || !sessionID) return null;
  try {
    const result = await client.session.get({ path: { id: sessionID } });
    return result?.data || result || null;
  } catch {
    return null;
  }
}

async function resolveWorktreeRouteForTest({ sessionID, data = {}, childRoles = {}, getSession, pathExists = existsSync }) {
  let currentID = sessionID;
  let inheritedParentRoute = false;
  let childRole = childRoles?.[sessionID]?.role || "unknown";
  const visited = new Set();
  for (let depth = 0; currentID && depth < 12 && !visited.has(currentID); depth += 1) {
    visited.add(currentID);
    const record = activeSessionRecord(currentID, data);
    if (record) {
      const decision = routingDecisionForTest({ session: record.session, pathExists });
      return {
        ...decision,
        repositorySessionID: record.id,
        topLevelOpenCodeSessionID: currentID,
        requestingOpenCodeSessionID: sessionID,
        inheritedParentRoute,
        childRole,
        session: record.session,
      };
    }
    const info = await getSession(currentID);
    const parentID = info?.parentID || "";
    if (currentID === sessionID && parentID && childRole === "unknown") {
      childRole = childRoleFromAgent(info?.agent || "");
    }
    if (parentID) inheritedParentRoute = true;
    currentID = parentID;
  }
  return {
    decision: "unresolved",
    worktreePath: "",
    repositorySessionID: "",
    topLevelOpenCodeSessionID: currentID || sessionID || "",
    requestingOpenCodeSessionID: sessionID || "",
    inheritedParentRoute,
    childRole,
    session: null,
  };
}

async function resolveWorktreeRoute(client, sessionID, data = sessionsData()) {
  return resolveWorktreeRouteForTest({
    sessionID,
    data,
    childRoles: presenceData().child_roles || {},
    getSession: (candidateID) => openCodeSession(client, candidateID),
  });
}

function isReadOnlyChildBash(command) {
  const safeCommand = (() => {
    let unsafeSubstitution = false;
    const replaced = String(command || "").replace(/\$\(\s*git\s+merge-base\s+([A-Za-z0-9_./:@^~-]+)\s+([A-Za-z0-9_./:@^~-]+)\s*\)/g, "SAFE_MERGE_BASE");
    if (replaced.includes("$(")) unsafeSubstitution = true;
    return unsafeSubstitution ? "" : replaced;
  })();
  if (!safeCommand) return false;
  const hasUnsafeExpansion = (() => {
    let quote = "";
    let escaped = false;
    for (const char of safeCommand) {
      if (escaped) {
        escaped = false;
        continue;
      }
      if (char === "\\" && quote !== "'") {
        escaped = true;
        continue;
      }
      if (quote === "'") {
        if (char === "'") quote = "";
        continue;
      }
      if (!quote && char === "'") {
        quote = "'";
        continue;
      }
      if (char === '"') {
        quote = quote === '"' ? "" : '"';
        continue;
      }
      if (char === "$" || char === "`" || (!quote && "{}*?[~".includes(char))) return true;
    }
    return quote !== "";
  })();
  if (hasUnsafeExpansion || ["<(", ">("].some((token) => safeCommand.includes(token)) || extractWriteTargets(safeCommand).length > 0) return false;
  const readOnlyCommands = new Set(["cat", "cut", "head", "jq", "nl", "pgrep", "ps", "pwd", "rg", "tail", "uniq", "wc"]);
  const readOnlyGitCommands = new Set(["blame", "branch", "describe", "diff", "log", "ls-files", "ls-tree", "merge-base", "name-rev", "rev-parse", "show", "status"]);
  const readOnlyDockerCommands = new Set(["inspect", "logs", "ps", "stats", "top"]);
  const readOnlyDebugSpecs = {
    chat: { booleanOptions: new Set(), valueOptions: new Set(), positional: 1 },
    issue: { booleanOptions: new Set(["--production", "--timeline"]), valueOptions: new Set(), positional: 1 },
    logs: { booleanOptions: new Set(["--o2"]), valueOptions: new Set(["--query-json"]), positional: 0 },
  };
  const readOnlyIssueSpecs = {
    show: { booleanOptions: new Set(["--full", "--json", "--no-logs"]), valueOptions: new Set(["--env"]), positional: 1 },
    timeline: { booleanOptions: new Set(["--compact"]), valueOptions: new Set(["--env"]), positional: 1 },
  };
  const readOnlyTestSpecs = {
    status: { booleanOptions: new Set(["--json"]), valueOptions: new Set(), positional: 0 },
    triage: { booleanOptions: new Set(["--json"]), valueOptions: new Set(), positional: 0 },
  };
  const readOnlyTraceSpecs = {
    errors: { booleanOptions: new Set(["--production"]), valueOptions: new Set(["--last", "--route"]), positional: 0 },
    login: { booleanOptions: new Set(["--production"]), valueOptions: new Set(["--user"]), positional: 0 },
    request: { booleanOptions: new Set(["--production"]), valueOptions: new Set(["--id"]), positional: 0 },
    task: { booleanOptions: new Set(["--production"]), valueOptions: new Set(["--id"]), positional: 0 },
  };
  const argumentsMatch = (args, spec) => {
    if (!spec) return false;
    let positional = 0;
    const seenOptions = new Set();
    for (let index = 0; index < args.length; index += 1) {
      const arg = args[index];
      if (!arg.startsWith("-")) {
        positional += 1;
        continue;
      }
      const option = arg.split("=", 1)[0];
      if (seenOptions.has(option)) return false;
      seenOptions.add(option);
      if (spec.booleanOptions.has(option)) {
        if (arg !== option) return false;
        continue;
      }
      if (!spec.valueOptions.has(option)) return false;
      if (arg.includes("=")) {
        if (arg.slice(arg.indexOf("=") + 1).startsWith("-")) return false;
      } else {
        index += 1;
        if (index >= args.length || args[index].startsWith("-")) return false;
      }
    }
    return positional === spec.positional;
  };
  const debugCommandIsReadOnly = (action, args) => {
    if (action === "trace") return argumentsMatch(args.slice(1), readOnlyTraceSpecs[args[0]]);
    return argumentsMatch(args, readOnlyDebugSpecs[action]);
  };
  const issueCommandIsReadOnly = (args) => {
    if (args.length === 1 && ["-h", "--help"].includes(args[0])) return true;
    const action = args[0];
    return argumentsMatch(args.slice(1), readOnlyIssueSpecs[action]);
  };
  const sessionCommandIsReadOnly = (args) => {
    if (args.length === 1 && ["-h", "--help"].includes(args[0])) return true;
    if (args[0] !== "chat" || !["read", "search"].includes(args[1])) return false;
    if (args[1] === "read") return args.length >= 3 && !args.slice(2).some((arg) => arg.startsWith("--out") || arg === "--write");
    return args.length >= 4 && !args.slice(2).some((arg) => arg.startsWith("--out") || arg === "--write");
  };

  return commandSegmentTokens(safeCommand.replace(/\\\s*\n/g, " ")).every((tokens) => {
    if (isAssignment(tokens[0] || "") || basename(unquote(tokens[0] || "")) === "env") return false;
    const directScript = unquote(tokens[0] || "").replace(/^\.\//, "");
    if (directScript === "scripts/issues.py") return issueCommandIsReadOnly(tokens.slice(1));
    const invocation = normalizedInvocation(tokens);
    const commandName = invocation.command;
    const args = invocation.args;
    if (commandName === "rg") {
      const executionOptions = ["--pre", "--pre-glob", "--hostname-bin", "--search-zip"];
      return !args.some((arg) => executionOptions.some((option) => arg === option || arg.startsWith(`${option}=`)));
    }
    if (commandName === "sort") {
      const mutatingOrExecutingOption = args.some((arg) => (
        /^-[^-]*o/.test(arg)
        || arg === "--output"
        || arg.startsWith("--output=")
        || arg === "--compress-program"
        || arg.startsWith("--compress-program=")
      ));
      return !mutatingOrExecutingOption;
    }
    if (readOnlyCommands.has(commandName)) return true;
    if (commandName === "git") {
      const unsafeGitOptions = ["-c", "--config-env", "--exec-path", "--ext-diff", "--paginate", "--textconv"];
      const hasUnsafeOption = args.some((arg) => unsafeGitOptions.some((option) => arg === option || arg.startsWith(`${option}=`)));
      const writesOutput = args.some((arg) => arg === "-o" || arg === "--output" || arg.startsWith("--output="));
      return !hasUnsafeOption && !writesOutput && readOnlyGitCommands.has(firstNonOption(args));
    }
    if (commandName === "gh") {
      return args[0] === "run" && args[1] === "view" && args.slice(2).every((arg) => !["--delete", "--cancel", "--rerun"].includes(arg));
    }
    if (commandName === "docker") {
      const action = args[0];
      if (readOnlyDockerCommands.has(action)) return true;
      if (action !== "exec") return false;
      if (args[1] !== "api" || !["python", "python3"].includes(basename(args[2])) || args[3] !== "/app/backend/scripts/debug.py") return false;
      return debugCommandIsReadOnly(args[4], args.slice(5));
    }
    if (["python", "python3"].includes(commandName)) {
      const script = unquote(args[0] || "").replace(/^\.\//, "");
      if (script === "scripts/issues.py") return issueCommandIsReadOnly(args.slice(1));
      if (script === "scripts/sessions.py") return sessionCommandIsReadOnly(args.slice(1));
      if (script === "scripts/tests.py") return argumentsMatch(args.slice(2), readOnlyTestSpecs[args[1]]);
      return false;
    }
    return false;
  });
}

function childRepositorySessionCommand(command) {
  return commandSegmentTokens(String(command || "")).some((segment) => {
    const tokens = segment.map(shellUnescape);
    const moduleIndex = tokens.findIndex((token, index) => token === "scripts.sessions" && tokens[index - 1] === "-m");
    const scriptIndex = tokens.findIndex((token) => {
      const candidate = resolve(PROJECT_ROOT, token);
      return [candidate, canonicalPath(candidate)]
        .some((path) => path.replace(/\\/g, "/").endsWith("/scripts/sessions.py"));
    });
    const commandIndex = scriptIndex >= 0 ? scriptIndex + 1 : (moduleIndex >= 0 ? moduleIndex + 1 : -1);
    return commandIndex > 0
      && (tokens[commandIndex] === "start"
        || (tokens[commandIndex] === "worktree" && tokens[commandIndex + 1] === "ensure"));
  });
}

function childMutationDecisionForTest(route, tool, command = "") {
  if (!route?.inheritedParentRoute || (!EDIT_TOOLS.has(tool) && !BASH_TOOLS.has(tool))) {
    return { decision: "allow", message: "no inherited child mutation" };
  }
  if (route.childRole === "writable") {
    if (BASH_TOOLS.has(tool) && childRepositorySessionCommand(command)) {
      return {
        decision: "block",
        message: actionable(
          "[OpenMates child ownership guard]",
          "a writable child must reuse the parent repository session and worktree",
          "continue the assigned mutation in the inherited parent worktree; do not start or ensure a child repository session.",
        ),
      };
    }
    return { decision: "allow", message: "writable child shares the parent worktree" };
  }
  if (BASH_TOOLS.has(tool) && isReadOnlyChildBash(command)) {
    return { decision: "allow", message: "read-only inherited child shell" };
  }
  const role = route.childRole || "unknown";
  return {
    decision: "block",
    message: actionable(
      "[OpenMates child ownership guard]",
      `child role ${role} may read the parent worktree but may not mutate it`,
      "finish the read-only investigation and return the finding to the parent; do not start another repository session.",
    ),
  };
}

function routingRecoveryMessage(sessionID) {
  return `${ROUTING_GUARD_MARKER} Reason: no active sessions.py worktree could be resolved for OpenCode session ${sessionID || "<unknown>"}. Next: run python3 scripts/sessions.py start --mode <feature|bug|docs|testing|question> --task \"brief description\". Safe reads, searches, approved audits, status, summary, context, worktree ensure, and worktree repair remain available.`;
}

function directPythonScriptArgs(command) {
  if (hasUnsafeLocalShellExpansionOrRedirection(command)) return null;
  const segments = commandSegmentTokens(String(command || ""));
  if (segments.length !== 1) return null;
  const tokens = segments[0].map(shellUnescape);
  if (!["python", "python3"].includes(tokens[0] || "")) return null;
  return tokens.slice(1);
}

function optionsMatch(args, { booleanOptions = new Set(), valueOptions = new Map() } = {}) {
  const seen = new Set();
  for (let index = 0; index < args.length; index += 1) {
    const option = args[index];
    if (seen.has(option)) return false;
    seen.add(option);
    if (booleanOptions.has(option)) continue;
    const validate = valueOptions.get(option);
    if (!validate || index + 1 >= args.length || !validate(args[index + 1])) return false;
    index += 1;
  }
  return true;
}

function isApprovedControlPlaneAuditCommand(command) {
  const args = directPythonScriptArgs(command);
  if (!args?.length) return false;
  const [script, ...options] = args;
  if (script === "scripts/audit_opencode_output_quality.py") {
    return optionsMatch(options, {
      booleanOptions: new Set(["--json"]),
      valueOptions: new Map([["--telemetry-days", (value) => /^\d+$/.test(value) && Number(value) >= 1 && Number(value) <= 168]]),
    });
  }
  if (script === "scripts/audit_agent_tooling_parity.py") {
    return optionsMatch(options, { booleanOptions: new Set(["--json"]) });
  }
  if (script === "scripts/audit_opencode_spec_workflow.py") return options.length === 0;
  if (script === "scripts/audit_opencode_automation_budget.py") {
    return optionsMatch(options, { booleanOptions: new Set(["--all"]) });
  }
  return false;
}

function exactCommitDeployedTestForTest(command, expectedCommit = "") {
  const args = directPythonScriptArgs(command);
  if (!args || args[0] !== "scripts/tests.py" || args[1] !== "run") return null;
  const options = args.slice(2);
  const values = {};
  const booleans = new Set();
  const allowedBoolean = new Set(["--gate-deploy", "--require-exact-commit", "--detach"]);
  const allowedValue = new Set(["--spec", "--expected-commit", "--proof-video-profile"]);
  for (let index = 0; index < options.length; index += 1) {
    const option = options[index];
    if (allowedBoolean.has(option)) {
      if (booleans.has(option)) return null;
      booleans.add(option);
      continue;
    }
    if (!allowedValue.has(option) || Object.hasOwn(values, option) || index + 1 >= options.length) return null;
    values[option] = options[++index];
  }
  const commit = values["--expected-commit"] || "";
  // The deployment gate plus a full expected SHA is safe for merged-worktree
  // routing even without strict HEAD equality. tests.py then accepts a newer
  // dev subject only when the requested spec's known inputs are unchanged.
  if (!booleans.has("--gate-deploy")) return null;
  if (!/^(?!.*(?:^|\/)\.\.(?:\/|$))[A-Za-z0-9][A-Za-z0-9._\/-]*\.spec\.ts$/.test(values["--spec"] || "")) return null;
  if (!/^[0-9a-f]{40}$/i.test(commit)) return null;
  if (expectedCommit && commit.toLowerCase() !== String(expectedCommit).toLowerCase()) return null;
  if (values["--proof-video-profile"] && !["web-phone", "web-laptop"].includes(values["--proof-video-profile"])) return null;
  return { commit, spec: values["--spec"] };
}

function isRecoveryBash(command) {
  if (isProdSshRecoveryCommand(command)) return true;
  if (improvementReviewCommandIsSafe(command)) return true;
  return /python3\s+scripts\/sessions\.py\s+(?:start|status|summary|context|doctor|spawn-chat)\b/.test(command)
    || /python3\s+scripts\/sessions\.py\s+worktree\s+(?:ensure|repair)\b/.test(command)
    || /python3\s+scripts\/sessions\.py\s+end\b[^;&|\n]*\s--force\b/.test(command)
    || isApprovedControlPlaneAuditCommand(command)
    || /^\s*(?:pwd|date|git\s+(?:status|log|diff|show)\b)/.test(command);
}

function improvementReviewCommandIsSafe(command) {
  const segments = commandSegmentTokens(String(command || "").replace(/\\\s*\n/g, " "));
  if (segments.length !== 1 || hasUnsafeLocalShellExpansionOrRedirection(command)) return false;
  const tokens = segments[0].map(shellUnescape);
  if (!["python", "python3"].includes(tokens[0]) || tokens[1] !== "scripts/opencode_chat_improvement_review.py") return false;
  const args = tokens.slice(2);
  let dryRunSeen = false;
  let hoursSeen = false;
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === "--dry-run-notify" && !dryRunSeen) {
      dryRunSeen = true;
      continue;
    }
    if (args[index] === "--hours" && /^\d+$/.test(args[index + 1] || "")) {
      if (hoursSeen || Number(args[index + 1]) < 1 || Number(args[index + 1]) > 168) return false;
      hoursSeen = true;
      index += 1;
      continue;
    }
    return false;
  }
  return dryRunSeen;
}

function isProdSshRecoveryCommand(command) {
  const segments = commandSegmentTokens(String(command || "").replace(/\\\s*\n/g, " "));
  if (segments.length !== 1) return false;
  const tokens = segments[0];
  let index = 0;
  while (index < tokens.length && isAssignment(tokens[index])) index += 1;
  const executable = shellUnescape(tokens[index] || "");
  const args = tokens.slice(index + 1).map(shellUnescape);
  const helpers = new Set([
    "./scripts/prod-ssh.sh",
    "scripts/prod-ssh.sh",
    `${PROJECT_ROOT}/scripts/prod-ssh.sh`,
  ]);
  return helpers.has(executable) && args.length === 1 && ["close", "status"].includes(args[0]);
}

function routingFailureForTest({ tool = "", sessionID = "", command = "", routeMessage = "", routeDecision = "", mergedCommit = "" } = {}) {
  if (READ_TOOLS.has(tool) || SEARCH_TOOLS.has(tool)) return { decision: "allow_read", message: "" };
  if (BASH_TOOLS.has(tool) && (isRecoveryBash(command) || isReadOnlyChildBash(command))) return { decision: "allow_recovery", message: "" };
  if (BASH_TOOLS.has(tool) && routeDecision === "merged_worktree" && exactCommitDeployedTestForTest(command, mergedCommit)) {
    return { decision: "allow_merged_verification", message: "" };
  }
  if (routeMessage) return { decision: "block", message: routeMessage };
  return { decision: "block", message: routingRecoveryMessage(sessionID) };
}

function isSharedRuntimeReadPath(candidate, worktreePath) {
  if (!candidate) return false;
  const absolute = isAbsolute(candidate) ? resolve(candidate) : resolve(worktreePath, candidate);
  return [resolve(worktreePath), resolve(PROJECT_ROOT)].some((base) => {
    const relativePath = relative(base, absolute);
    return relativePath === "logs/nightly-reports" || relativePath.startsWith(`logs${sep}nightly-reports${sep}`);
  });
}

function approvedSharedRuntimeRelativePath(candidate, worktreePath) {
  if (!candidate) return "";
  const absolute = isAbsolute(candidate) ? resolve(candidate) : resolve(worktreePath, candidate);
  const worktreeRelative = relative(resolve(worktreePath), absolute);
  const rootRelative = relative(resolve(PROJECT_ROOT), absolute);
  const relativePath = !worktreeRelative.startsWith("..") && !isAbsolute(worktreeRelative)
    ? worktreeRelative
    : (!rootRelative.startsWith("..") && !isAbsolute(rootRelative) ? rootRelative : "");
  if (
    relativePath === ".claude/sessions.json"
    || relativePath === ".opencode/presence.json"
    || relativePath === "test-results"
    || relativePath.startsWith(`test-results${sep}`)
  ) return relativePath;
  return "";
}

function sharedRuntimeFallback(candidate, worktreePath) {
  const relativePath = approvedSharedRuntimeRelativePath(candidate, worktreePath);
  if (!relativePath) return "";
  const worktreeTarget = resolve(worktreePath, relativePath);
  return existsSync(worktreeTarget) ? worktreeTarget : resolve(PROJECT_ROOT, relativePath);
}

function isSharedSecretRuntimePath(candidate, worktreePath) {
  if (!candidate) return false;
  const absolute = isAbsolute(candidate) ? resolve(candidate) : resolve(worktreePath, candidate);
  return [resolve(worktreePath), resolve(PROJECT_ROOT)].some((base) => relative(base, absolute) === ".env");
}

function isApprovedControlPlaneRuntimeSearchPath(candidate) {
  if (!candidate || !isAbsolute(candidate)) return false;
  const relativePath = relative(resolve(CURRENT_CONTROL_PLANE_ROOT), resolve(candidate));
  return relativePath === "test-results" || relativePath.startsWith(`test-results${sep}`);
}

function approvedProofVideoSourceTokenForTest(command) {
  if (hasUnsafeLocalShellExpansionOrRedirection(command)) return "";
  const segments = commandSegmentTokens(String(command || ""));
  if (segments.length !== 1) return "";
  const tokens = segments[0].map(shellUnescape);
  let index = 0;
  while (index < tokens.length && isAssignment(tokens[index])) index += 1;
  if (!["python", "python3"].includes(tokens[index] || "")) return "";
  if ((tokens[index + 1] || "").replace(/^\.\//, "") !== "scripts/sessions.py") return "";
  if (tokens[index + 2] !== "proof-video" || tokens[index + 3] !== "produce-playwright") return "";

  let source = "";
  for (let cursor = index + 4; cursor < tokens.length; cursor += 1) {
    const token = tokens[cursor];
    if (token === "--source-video") {
      if (source || cursor + 1 >= tokens.length) return "";
      source = tokens[++cursor];
      continue;
    }
    if (token.startsWith("--source-video=")) {
      if (source) return "";
      source = token.slice("--source-video=".length);
    }
  }
  if (!source || !isAbsolute(source)) return "";
  const artifactRoot = resolve(PROJECT_ROOT, "test-results/proof-video-source-artifacts");
  const resolvedSource = resolve(source);
  const artifactRelative = relative(artifactRoot, resolvedSource);
  if (!artifactRelative || artifactRelative.startsWith("..") || isAbsolute(artifactRelative)) return "";
  return source;
}

function routeLocalToolArgsForTest(tool, args, worktreePath) {
  const input = toolInput(args);
  if (!worktreePath && BASH_TOOLS.has(tool)) {
    const command = bashCommand(input);
    const commandSegments = commandSegmentTokens(command);
    const hasControlPlaneScript = commandSegments.some(isCanonicalControlPlaneScriptSegment);
    const controlPlaneScriptRuntime = commandSegments.length > 0
      && commandSegments.every(isCanonicalControlPlaneScriptSegment);
    if (hasControlPlaneScript && !controlPlaneScriptRuntime) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: a canonical sessions.py/tests.py command is mixed with another shell command. Next: run the canonical control-plane command in its own tool call so it can use the clean runtime.`);
    }
    if (controlPlaneScriptRuntime) return { ...input, command, workdir: CURRENT_CONTROL_PLANE_ROOT };
  }
  if (!worktreePath) return input;
  if (BASH_TOOLS.has(tool)) {
    const command = bashCommand(input);
    if (command.includes("$'")) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: ANSI-C shell quoting can encode managed paths and bypass session isolation. Next: use ordinary quoted values and repository-relative paths inside ${worktreePath}.`);
    }
    const prodSshHelper = `${PROJECT_ROOT}/scripts/prod-ssh.sh`;
    const routedWorktree = resolve(worktreePath);
    const prodSshPaths = new Set([
      "./scripts/prod-ssh.sh",
      "scripts/prod-ssh.sh",
      `${routedWorktree}/scripts/prod-ssh.sh`,
      prodSshHelper,
    ]);
    const commandSegments = commandSegmentTokens(command);
    const prodSshSegment = commandSegments.findIndex((tokens) => {
      let index = 0;
      while (index < tokens.length && isAssignment(tokens[index])) index += 1;
      return prodSshPaths.has(shellUnescape(tokens[index]));
    });
    const prodSshTokens = prodSshSegment >= 0 ? commandSegments[prodSshSegment] : [];
    const directProdSshInvocation = commandSegments.length === 1
      && prodSshTokens.length >= 1
      && prodSshPaths.has(shellUnescape(prodSshTokens[0]));
    const prodSshOpenInvocation = prodSshTokens.length === 2
      && prodSshPaths.has(shellUnescape(prodSshTokens[0]))
      && shellUnescape(prodSshTokens[1]) === "open";
    const safeFeeder = commandSegments.length === 2
      && ["echo", "printf"].includes(shellUnescape(commandSegments[0][0]))
      && (command.match(/\|/g) || []).length === 1;
    const hasTopLevelSeparator = tokenizeCommand(command).some(isSeparator);
    const unsafeControlSyntax = hasUnsafeLocalShellExpansionOrRedirection(command);
    const prodSshControlPlane = prodSshSegment === commandSegments.length - 1
      && prodSshSegment >= 0
      && (directProdSshInvocation || (prodSshOpenInvocation && safeFeeder))
      && (!hasTopLevelSeparator || safeFeeder)
      && !unsafeControlSyntax;
    const staleCodeSegment = commandSegments.findIndex((tokens) => (
      ["python", "python3"].includes(shellUnescape(tokens[0]))
      && shellUnescape(tokens[1]) === "scripts/stale_code_daily.py"
    ));
    const staleCodeTokens = staleCodeSegment >= 0 ? commandSegments[staleCodeSegment] : [];
    const staleCodeArgs = staleCodeTokens.slice(2);
    let staleCodeArgsSafe = staleCodeArgs.includes("--dry-run-notify");
    for (let index = 0; index < staleCodeArgs.length && staleCodeArgsSafe; index += 1) {
      if (staleCodeArgs[index] === "--dry-run-notify") continue;
      if (staleCodeArgs[index] === "--limit" && /^\d+$/.test(staleCodeArgs[index + 1] || "")) {
        index += 1;
        continue;
      }
      staleCodeArgsSafe = false;
    }
    const staleCodeReportControlPlane = staleCodeTokens.length >= 3
      && commandSegments.length === 1
      && ["python", "python3"].includes(shellUnescape(staleCodeTokens[0]))
      && shellUnescape(staleCodeTokens[1]) === "scripts/stale_code_daily.py"
      && staleCodeArgsSafe
      && !hasTopLevelSeparator
      && !unsafeControlSyntax;
    if (staleCodeSegment >= 0 && !staleCodeReportControlPlane) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: stale-code report generation is root control-plane work and only the report-only dry-run form is allowed. Next: run python3 scripts/stale_code_daily.py --dry-run-notify with an optional numeric --limit.`);
    }
    const improvementReviewSegment = commandSegments.findIndex((tokens) => (
      ["python", "python3"].includes(shellUnescape(tokens[0]))
      && shellUnescape(tokens[1]) === "scripts/opencode_chat_improvement_review.py"
    ));
    const improvementReviewControlPlane = improvementReviewCommandIsSafe(command);
    if (improvementReviewSegment >= 0 && !improvementReviewControlPlane) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: OpenCode improvement review generation is root control-plane work and only the report-only dry-run form is allowed. Next: run python3 scripts/opencode_chat_improvement_review.py --hours 72 --dry-run-notify.`);
    }
    // Session lifecycle and test dispatch are shared control-plane operations,
    // not source-worktree operations. Never route a mixed compound expression
    // into the clean runtime: a trailing generator, git command, or redirect
    // could otherwise mutate that immutable checkout.
    const hasControlPlaneScript = commandSegments.some(isCanonicalControlPlaneScriptSegment);
    const controlPlaneScriptRuntime = commandSegments.length > 0
      && commandSegments.every(isCanonicalControlPlaneScriptSegment);
    if (hasControlPlaneScript && !controlPlaneScriptRuntime) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: a canonical sessions.py/tests.py command is mixed with another shell command, which could mutate the shared runtime checkout. Next: run the canonical control-plane command in its own tool call, then run any source-worktree command separately.`);
    }
    const normalizedTokens = tokenizeCommand(command).map(shellUnescape);
    const tokensWithoutOwnWorktree = normalizedTokens.map((token) => token.split(routedWorktree).join(""));
    const approvedProofSource = approvedProofVideoSourceTokenForTest(command);
    const rootReferences = tokensWithoutOwnWorktree.filter((token) => (
      token.includes(PROJECT_ROOT) && token !== approvedProofSource && token !== `--source-video=${approvedProofSource}`
    ));
    const rootHelperInvocations = commandSegmentTokens(command).filter((tokens) => {
      let index = 0;
      while (index < tokens.length && isAssignment(tokens[index])) index += 1;
      return shellUnescape(tokens[index]) === prodSshHelper;
    }).length;
    const exactRootHelperOnly = rootReferences.length > 0
      && rootReferences.every((token) => token === prodSshHelper)
      && rootHelperInvocations === rootReferences.length;
    const referencesOtherWorktree = tokensWithoutOwnWorktree.some((token) => WORKTREE_ROOTS.some((root) => token.includes(root)));
    if ((rootReferences.length > 0 && !exactRootHelperOnly) || referencesOtherWorktree) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: the shell command explicitly references the root checkout or another managed worktree and would bypass session isolation. Next: use repository-relative paths; this command will run with workdir=${worktreePath}.`);
    }
    const traversal = tokenizeCommand(command).find((token) => {
      const value = unquote(token);
      return value === ".." || value.startsWith("../") || value.includes("/../");
    });
    if (traversal) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: the shell command contains relative traversal (${traversal}) that could escape the routed worktree. Next: use paths inside ${worktreePath}.`);
    }
    return {
      ...input,
      command,
      workdir: (prodSshControlPlane || staleCodeReportControlPlane || improvementReviewControlPlane || controlPlaneScriptRuntime)
        ? (controlPlaneScriptRuntime ? CURRENT_CONTROL_PLANE_ROOT : PROJECT_ROOT)
        : worktreePath,
    };
  }
  if (SEARCH_TOOLS.has(tool)) {
    const routed = { ...input };
    if (typeof routed.path === "string" && isSharedSecretRuntimePath(routed.path, worktreePath)) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: .env is a shared secret runtime resource and cannot be read or searched directly. Next: run the repository script that consumes the required environment variables without printing them.`);
    }
    if (typeof routed.path === "string" && targetsDifferentWorktree(routed.path, worktreePath)) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: the absolute search path targets another managed worktree. Next: use a repository-relative path inside ${worktreePath}.`);
    }
    if (
      typeof routed.path === "string"
      && isAbsolute(routed.path)
      && pathEscapesWorktree(routed.path, worktreePath)
      && !pathInProjectRoot(routed.path)
      && !isApprovedControlPlaneRuntimeSearchPath(routed.path)
    ) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: the absolute search path is outside the routed worktree and approved test-results runtime. Next: search a repository-relative path inside ${worktreePath}, or use the exact artifact path under ${CURRENT_CONTROL_PLANE_ROOT}/test-results.`);
    }
    if (typeof routed.path === "string" && !isAbsolute(routed.path)) {
      const target = resolve(worktreePath, routed.path);
      if (pathEscapesWorktree(target, worktreePath) && !isSharedRuntimeReadPath(routed.path, worktreePath)) {
        throw new Error(`${ROUTING_GUARD_MARKER} Reason: the relative search path escapes the routed worktree. Next: use a path inside ${worktreePath}.`);
      }
    }
    const sharedFallback = sharedRuntimeFallback(routed.path, worktreePath);
    routed.path = sharedFallback || rewritePathForWorktree(routed.path || ".", worktreePath);
    return routed;
  }
  for (const key of ["file_path", "filePath", "path"]) {
    const value = input[key];
    if (typeof value !== "string") continue;
    if (isSharedSecretRuntimePath(value, worktreePath)) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: .env is a shared secret runtime resource and cannot be read or searched directly. Next: run the repository script that consumes the required environment variables without printing them.`);
    }
    if (targetsDifferentWorktree(value, worktreePath)) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: the absolute file path targets another managed worktree. Next: use a repository-relative path inside ${worktreePath}.`);
    }
    if (isAbsolute(value)) continue;
    const target = resolve(worktreePath, value);
    if (pathEscapesWorktree(target, worktreePath) && !isSharedRuntimeReadPath(value, worktreePath)) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: the relative file path escapes the routed worktree. Next: use a repository-relative path inside ${worktreePath}.`);
    }
  }
  if (READ_TOOLS.has(tool)) {
    for (const key of ["file_path", "filePath", "path"]) {
      if (typeof input[key] !== "string") continue;
      const sharedFallback = sharedRuntimeFallback(input[key], worktreePath);
      if (sharedFallback) return { ...input, [key]: sharedFallback };
    }
  }
  for (const line of (input.patchText || input.patch || "").split("\n")) {
    const prefix = ["*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: "]
      .find((candidate) => line.startsWith(candidate));
    if (!prefix) continue;
    const value = line.slice(prefix.length).trim();
    if (!value) continue;
    if (targetsDifferentWorktree(value, worktreePath)) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: an absolute patch path targets another managed worktree. Next: use repository-relative patch paths inside ${worktreePath}.`);
    }
    if (isAbsolute(value)) continue;
    const target = resolve(worktreePath, value);
    if (pathEscapesWorktree(target, worktreePath)) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: a patch path escapes the routed worktree. Next: use repository-relative patch paths inside ${worktreePath}.`);
    }
  }
  return rewriteEditArgsForTest(input, worktreePath);
}

function routeLocalToolArgsWithCircuitBreakerForTest(
  tool,
  args,
  worktreePath,
  { sessionID = "", counts = new Map() } = {},
) {
  try {
    return routeLocalToolArgsForTest(tool, args, worktreePath);
  } catch (error) {
    const command = bashCommand(args);
    const key = `isolation:${sessionID}:${tool}:${command}:${error.message}`;
    const count = (counts.get(key) || 0) + 1;
    counts.set(key, count);
    throw new Error(repeatedRoutingFailureMessageForTest(error.message, count));
  }
}

async function recordWorktreeRouting(opencodeSessionID) {
  if (!opencodeSessionID) return false;
  const result = await runProcess(
    "python3",
    ["scripts/sessions.py", "worktree", "repair", "--opencode-session", opencodeSessionID],
    { cwd: PROJECT_ROOT },
  );
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "routing repair failed").trim();
    warnOnceForTest(
      `${ROUTING_GUARD_MARKER} Reason: sessions.py could not record worktree routing. Next: run python3 scripts/sessions.py worktree repair --opencode-session ${opencodeSessionID}. Detail: ${detail}`,
      { sessionID: opencodeSessionID },
    );
    return false;
  }
  return true;
}

function createWorktreeCheckpointSchedulerForTest({ spawnProcess = spawn, warn = warnOnceForTest } = {}) {
  const inFlight = new Map();
  return (opencodeSessionID, event) => {
    if (!opencodeSessionID || !["idle", "closed"].includes(event)) return false;
    if (inFlight.has(opencodeSessionID)) return false;
    // Use the pinned clean control plane; sessions.py resolves shared state and the routed source worktree.
    const child = spawnProcess(
      "python3",
      [
        "scripts/sessions.py",
        "worktree",
        "checkpoint",
        "--opencode-session",
        opencodeSessionID,
        "--event",
        event,
      ],
      { cwd: CURRENT_CONTROL_PLANE_ROOT, env: process.env, detached: true, stdio: "ignore" },
    );
    inFlight.set(opencodeSessionID, child);
    const clear = () => {
      if (inFlight.get(opencodeSessionID) === child) inFlight.delete(opencodeSessionID);
    };
    child.on("error", (error) => {
      clear();
      warn(
        `${ROUTING_GUARD_MARKER} Reason: could not schedule ${event} checkpoint for ${opencodeSessionID}. The periodic reconciliation worker will retry. Detail: ${error.message}`,
        { sessionID: opencodeSessionID },
      );
    });
    child.on("close", (code) => {
      clear();
      if (code !== 0) {
        warn(
          `${ROUTING_GUARD_MARKER} Reason: ${event} checkpoint for ${opencodeSessionID} exited with status ${code}. The periodic reconciliation worker will retry.`,
          { sessionID: opencodeSessionID },
        );
      }
    });
    child.unref();
    return true;
  };
}

const scheduleWorktreeCheckpoint = createWorktreeCheckpointSchedulerForTest();

function createWorktreeActivationSchedulerForTest({ spawnProcess = spawn, warn = warnOnceForTest } = {}) {
  const inFlight = new Map();
  return (opencodeSessionID) => {
    if (!opencodeSessionID || inFlight.has(opencodeSessionID)) return false;
    const child = spawnProcess(
      "python3",
      ["scripts/sessions.py", "worktree", "activate", "--opencode-session", opencodeSessionID],
      { cwd: CURRENT_CONTROL_PLANE_ROOT, env: process.env, detached: true, stdio: "ignore" },
    );
    inFlight.set(opencodeSessionID, child);
    const clear = () => {
      if (inFlight.get(opencodeSessionID) === child) inFlight.delete(opencodeSessionID);
    };
    child.on("error", (error) => {
      clear();
      warn(
        `${ROUTING_GUARD_MARKER} Reason: could not mark ${opencodeSessionID} active after a user message. Automatic integration remains protected by live presence. Detail: ${error.message}`,
        { sessionID: opencodeSessionID },
      );
    });
    child.on("close", (code) => {
      clear();
      if (code !== 0) {
        warn(
          `${ROUTING_GUARD_MARKER} Reason: worktree activation for ${opencodeSessionID} exited with status ${code}. Automatic integration remains protected by live presence.`,
          { sessionID: opencodeSessionID },
        );
      }
    });
    child.unref();
    return true;
  };
}

const scheduleWorktreeActivation = createWorktreeActivationSchedulerForTest();

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

function rewriteEditArgsForTest(args, worktreePath) {
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

function openMatesServerLifecycleMutation(command) {
  for (const tokens of commandSegmentTokens(command.replace(/\\\s*\n/g, " "))) {
    const invocation = normalizedInvocation(tokens);
    const { command: commandName, args } = invocation;
    if (commandName !== "openmates") continue;
    if (args[0] !== "server") continue;
    if (["restart", "start", "stop", "update"].includes(args[1])) return true;
  }
  return false;
}

function dockerMutationDecisionForTest({ command = "" } = {}) {
  if (openMatesServerLifecycleMutation(command)) {
    return {
      decision: "block",
      message: actionable(
        DOCKER_LIFECYCLE_MARKER,
        "OpenMates server lifecycle commands spawn Docker Compose and bypass the shared restart coordinator in agent sessions.",
        "use python3 scripts/sessions.py docker restart --session <repository-session-id> --service <service> [--build], or wait with python3 scripts/sessions.py wait-lock --session <repository-session-id> --type docker --follow --poll 10.",
      ),
    };
  }
  if (!dockerComposeMutation(command)) return { decision: "allow", message: "not a Docker lifecycle mutation" };
  return {
    decision: "block",
    message: actionable(
      DOCKER_LIFECYCLE_MARKER,
      "Direct Docker Compose lifecycle mutations bypass the registered OpenMates source and service policy.",
      "use python3 scripts/sessions.py docker restart --session <repository-session-id> --service <service> [--build], or wait with python3 scripts/sessions.py wait-lock --session <repository-session-id> --type docker --follow --poll 10.",
    ),
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
    throw new Error(actionable("[OpenMates source write guard]", "Bash would mutate repository source outside the reviewable edit path.", "use apply_patch for source-file changes."));
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
      throw new Error(actionable("[OpenMates test command guard]", "direct local Vitest bypasses the test control plane.", "run python3 scripts/tests.py run --suite vitest."));
    }
    if (commandName === "playwright" && firstArg === "test") {
      throw new Error(actionable("[OpenMates test command guard]", "direct local Playwright bypasses deployed-code verification.", "run python3 scripts/tests.py run --spec <name>.spec.ts or --suite playwright."));
    }
    if (commandName === "pnpm" && ["test", "vitest"].includes(firstArg)) {
      throw new Error(actionable("[OpenMates test command guard]", "pnpm test bypasses the Vitest control plane.", "run python3 scripts/tests.py run --suite vitest."));
    }
    if (commandName === "pnpm" && firstArg === "playwright" && secondArg === "test") {
      throw new Error(actionable("[OpenMates test command guard]", "pnpm Playwright bypasses deployed-code verification.", "run python3 scripts/tests.py run --spec <name>.spec.ts or --suite playwright."));
    }
    if (commandName === "npx" && firstArg === "vitest") {
      throw new Error(actionable("[OpenMates test command guard]", "npx Vitest bypasses the test control plane.", "run python3 scripts/tests.py run --suite vitest."));
    }
    if (commandName === "npx" && firstArg === "playwright" && secondArg === "test") {
      throw new Error(actionable("[OpenMates test command guard]", "npx Playwright bypasses deployed-code verification.", "run python3 scripts/tests.py run --spec <name>.spec.ts or --suite playwright."));
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

function changesOpenCodeSessionEnvironment(tokens) {
  let index = 0;
  while (index < tokens.length && isAssignment(tokens[index])) {
    if (shellUnescape(tokens[index]).startsWith("OPENCODE_SESSION_ID=")) return true;
    index += 1;
  }
  let commandName = basename(tokens[index] || "");
  if (["command", "builtin"].includes(commandName)) {
    index += 1;
    while (index < tokens.length && isAssignment(tokens[index])) {
      if (shellUnescape(tokens[index]).startsWith("OPENCODE_SESSION_ID=")) return true;
      index += 1;
    }
    commandName = basename(tokens[index] || "");
  }
  if (commandName !== "env") return false;
  for (let envIndex = index + 1; envIndex < tokens.length; envIndex += 1) {
    const token = shellUnescape(tokens[envIndex] || "");
    if (token === "--") return false;
    if (token.startsWith("OPENCODE_SESSION_ID=")) return true;
    if (token === "-i" || token === "--ignore-environment") return true;
    if (token === "-u" || token === "--unset") {
      if (shellUnescape(tokens[envIndex + 1] || "") === "OPENCODE_SESSION_ID") return true;
      envIndex += 1;
      continue;
    }
    if (token.startsWith("--unset=") && token.slice("--unset=".length) === "OPENCODE_SESSION_ID") return true;
    if (isAssignment(token) || isOption(token)) continue;
    return false;
  }
  return false;
}

function hasOpenCodeSessionEnvironmentChange(tokens) {
  for (let index = 0; index < tokens.length; index += 1) {
    const token = shellUnescape(tokens[index] || "");
    if (token.startsWith("OPENCODE_SESSION_ID=")) return true;
    if (token === "-i" || token === "--ignore-environment") return true;
    if ((token === "-u" || token === "--unset") && shellUnescape(tokens[index + 1] || "") === "OPENCODE_SESSION_ID") return true;
    if (token.startsWith("--unset=") && token.slice("--unset=".length) === "OPENCODE_SESSION_ID") return true;
  }
  return false;
}

function isCanonicalControlPlaneScriptSegment(tokens) {
  let index = 0;
  while (index < tokens.length && isAssignment(shellUnescape(tokens[index] || ""))) index += 1;
  if (!["python", "python3"].includes(shellUnescape(tokens[index] || ""))) return false;
  const script = shellUnescape(tokens[index + 1] || "").replace(/^\.\//, "");
  return script === "scripts/sessions.py" || script === "scripts/tests.py";
}

function isTestsScriptToken(token) {
  const script = shellUnescape(token || "").replace(/^\.\//, "");
  return script === "scripts/tests.py" || script.endsWith("/scripts/tests.py");
}

function testsCampaignVerbFromTokens(tokens) {
  for (let index = 0; index < tokens.length - 2; index += 1) {
    if (isTestsScriptToken(tokens[index]) && shellUnescape(tokens[index + 1] || "") === "campaign") {
      return shellUnescape(tokens[index + 2] || "");
    }
  }
  return "";
}

function mutatingCampaignVerbFromText(command) {
  const text = String(command || "");
  const shellMatch = text.match(/(?:^|[\s"'`])(?:\.\/|[^\s"'`]+\/)?scripts\/tests\.py\s+campaign\s+([a-z-]+)/);
  const codeMatch = text.match(/scripts\/tests\.py["']?\s*,\s*["']campaign["']?\s*,\s*["']([a-z-]+)/);
  const verb = shellMatch?.[1] || codeMatch?.[1] || "";
  return verb && !new Set(["status", "worker-state"]).has(verb) ? verb : "";
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
  const failedSummary = /\bFailed:\s*[1-9]\d*\b/i.test(text)
    || /\bDispatch errors:\s*[1-9]\d*\b/i.test(text)
    || /\b(?:result_unknown|dispatch_error|timed out)\b/i.test(text);
  if (/scripts\/tests\.py\s+run\b/.test(command) && failedSummary) {
    suggestions.push("If this is daily-failure debugging, claim a failure lease before editing: python3 scripts/tests.py next --lease --session ${OPENCODE_SESSION_ID:-manual}. Then rerun with --lease-required --lease-id <lease>.");
  }
  if (!suggestions.length) return;
  output.output += `

${COMMAND_DOCTOR_MARKER}
${suggestions.map((suggestion) => `- ${suggestion}`).join("\n")}`;
}

function taskChildClassificationForTest(input, output) {
  if (!TASK_TOOLS.has(input?.tool || "")) return null;
  const metadata = output?.metadata || output?.state?.metadata || {};
  const outputText = String(output?.output || output?.state?.output || "");
  const parentID = String(metadata.parentSessionId || input?.sessionID || "");
  const sessionID = String(
    metadata.sessionId
    || outputText.match(/<task\s+id=["'](ses_[A-Za-z0-9]+)["']/)?.[1]
    || "",
  );
  const subagentType = String((input?.args || {}).subagent_type || "");
  if (!parentID || parentID !== input?.sessionID || !sessionID) return null;
  const role = childRoleFromAgent(subagentType);
  return role === "unknown" ? null : { sessionID, parentID, role };
}

function reviewerSpawnDecisionForTest({ agent = "", generation = 0, lastReviewedGeneration } = {}) {
  if (!REVIEWER_SUBAGENTS.has(String(agent))) {
    return { decision: "allow", message: "task is not a reviewer" };
  }
  if (lastReviewedGeneration === generation) {
    return {
      decision: "block",
      message: actionable(
        "[OpenMates reviewer loop guard]",
        "this source revision already has a completed code-reviewer pass.",
        "address the existing findings or continue verification; spawn another reviewer only after a source edit creates a new revision.",
      ),
    };
  }
  return { decision: "allow", message: "source changed since the previous reviewer" };
}

function toolNameMatches(tool, expected) {
  return String(tool || "").toLowerCase() === expected.toLowerCase();
}

function isTodoWriteTool(tool) {
  return ["todowrite", "todo_write", "todo.write", "TodoWrite"].includes(String(tool || ""));
}

function presenceIsLive(state) {
  return PRESENCE_LIVE_EXECUTION.has(state?.execution) || state?.turn === "streaming";
}

function todoListFromToolArgs(args) {
  const input = toolInput(args);
  return Array.isArray(input.todos) ? input.todos : [];
}

function completedAssistantMessageID(event) {
  if (!["message.updated", "message.completed", "assistant.completed"].includes(event?.type)) return "";
  const info = event?.properties?.info || {};
  const role = info.role || event?.properties?.role || event?.properties?.message?.role || "";
  const messageID = info.id || event?.properties?.messageID || event?.properties?.id || event?.properties?.message?.id || "";
  const completed = info.time?.completed || info.timeCompleted || event?.properties?.time?.completed || event?.properties?.completed || event?.properties?.message?.time?.completed;
  const error = info.error || event?.properties?.error || event?.properties?.message?.error;
  if (role !== "assistant" || !completed || error) return "";
  return String(messageID || "");
}

function notifierEventArgsForTest({ eventType = "", sessionID = "", messageID = "", todos = [] } = {}) {
  if (!sessionID) return [];
  if (eventType === "response-completed") {
    return [OPENCODE_NOTIFIER, "--event", "response-completed", "--session-id", sessionID, "--message-id", messageID || ""];
  }
  return [];
}

function scheduleNotifierEvent(args) {
  if (!args.length || !existsSync(OPENCODE_NOTIFIER)) return;
  mkdirSync(`${PROJECT_ROOT}/logs`, { recursive: true });
  const logFd = openSync(OPENCODE_NOTIFIER_LOG, "a");
  try {
    const child = spawn("python3", args, {
      cwd: PROJECT_ROOT,
      env: process.env,
      detached: true,
      stdio: ["ignore", logFd, logFd],
    });
    child.on("error", (error) => {
      console.warn(`[OpenMates event notifier] failed to spawn: ${error?.message || error}`);
    });
    child.unref();
  } finally {
    closeSync(logFd);
  }
}

async function recordTaskChildRole(input, output) {
  const classification = taskChildClassificationForTest(input, output);
  if (!classification) return;
  const result = await runProcess(
    "python3",
    [
      "scripts/sessions.py",
      "presence",
      "child-role",
      "--session",
      classification.sessionID,
      "--parent",
      classification.parentID,
      "--role",
      classification.role,
      "--if-unset",
    ],
    { cwd: PROJECT_ROOT },
  );
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "unknown error").trim();
    console.warn(`[OpenMates presence diagnostic] Could not record task child role: ${detail}`);
  }
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

function temporaryLockWaitTypesForTest(text) {
  const lockTypes = new Set();
  const value = String(text || "");
  if (/active lock\(s\):[^\n]*\bdocker_rebuild\b|BLOCKED:[^\n]*\bdocker_rebuild\b[^\n]*lock held|\bdocker_rebuild:\s*IN_PROGRESS/i.test(value)) {
    lockTypes.add("docker");
  }
  if (/active lock\(s\):[^\n]*\bvercel_deploy\b|BLOCKED:[^\n]*\bvercel_deploy\b[^\n]*lock held|\bvercel_deploy:\s*IN_PROGRESS/i.test(value)) {
    lockTypes.add("vercel");
  }
  return [...lockTypes];
}

function appendTemporaryLockWaitHint(output) {
  if (!output || typeof output.output !== "string" || output.output.includes(TEMPORARY_LOCK_WAIT_MARKER)) return;
  const lockTypes = temporaryLockWaitTypesForTest(output.output);
  if (!lockTypes.length) return;
  const commands = lockTypes.map(
    (lockType) => `  python3 scripts/sessions.py wait-lock --session \${OPENCODE_SESSION_ID:-manual} --type ${lockType} --follow --poll 10`,
  );
  output.output += `

${TEMPORARY_LOCK_WAIT_MARKER}
This is temporary resource contention, not a terminal blocker. Do not finish this response as blocked.
Run the matching deterministic waiter with a sufficiently long Bash timeout, wait for OPENMATES_WAIT_READY, then continue the interrupted operation in this same response:
${commands.join("\n")}`;
}

function apiHealthWaitUrlForTest(text) {
  const value = String(text || "");
  if (!/(?:\b502\b|Bad Gateway|health returned|health check|ECONNREFUSED|connection refused|upstream connect error)/i.test(value)) {
    return "";
  }
  const match = value.match(/https:\/\/api\.dev\.openmates\.org\/health\b/i);
  if (match) return match[0];
  if (/api\.dev\.openmates\.org/i.test(value) && /health|502|Bad Gateway/i.test(value)) {
    return "https://api.dev.openmates.org/health";
  }
  return "";
}

function appendApiHealthWaitHint(output) {
  if (!output || typeof output.output !== "string" || output.output.includes(API_HEALTH_WAIT_MARKER)) return;
  const url = apiHealthWaitUrlForTest(output.output);
  if (!url) return;
  output.output += `

${API_HEALTH_WAIT_MARKER}
Shared dev API health is a coordinated runtime resource, not something every chat should investigate independently.
Run the deterministic waiter with a sufficiently long Bash timeout:
  python3 scripts/sessions.py wait-health --session \${OPENCODE_SESSION_ID:-manual} --url ${url} --follow --poll 10
If it prints OPENMATES_HEALTH_READY, continue the interrupted proof/test. If it prints OPENMATES_HEALTH_INVESTIGATE, this chat is the single incident owner; diagnose/restart via sessions.py docker only. Other chats should keep waiting.`;
}

function sleepDurationSecondsForTest(value) {
  const match = String(value || "").trim().match(/^(\d+(?:\.\d+)?)([smhd]?)$/i);
  if (!match) return null;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount)) return null;
  const unit = match[2].toLowerCase();
  if (unit === "d") return amount * 86_400;
  if (unit === "h") return amount * 3_600;
  if (unit === "m") return amount * 60;
  return amount;
}

function opaqueLongSleepDecisionForTest(command) {
  const tokens = tokenizeCommand(command);
  for (let index = 0; index < tokens.length; index += 1) {
    if (basename(tokens[index]) !== "sleep") continue;
    const durations = collectCommandArguments(tokens, index)
      .filter((arg) => !isOption(arg))
      .map((arg) => sleepDurationSecondsForTest(arg))
      .filter((seconds) => seconds !== null);
    if (durations.some((seconds) => seconds >= 10)) {
      return {
        decision: "block",
        message: actionable(
          OPAQUE_LONG_SLEEP_MARKER,
          "direct sleep commands of 10 seconds or longer create redundant assistant-side polling even when the real test, deploy, lock, health, or detached process already has a deterministic completion signal",
          "block on the real operation with a long tool timeout: use `python3 scripts/sessions.py wait-lock ...`, `python3 scripts/sessions.py wait-health ...`, `gh run watch <id> --exit-status`, or `tail --pid=<pid> -f /dev/null`; then read the final result once",
        ),
      };
    }
  }
  return { decision: "allow", message: "" };
}

function firstResponseMediaVideoSnippetForTest(text) {
  const match = String(text || "").match(/<video\b[\s\S]*?<\/video>/i);
  return match ? match[0] : "";
}

function responseMediaVideoProducerCommandForTest(command) {
  const value = String(command || "");
  if (/scripts\/(?:tests\.py\s+run|cli_video_capture\.py)\b/.test(value)) return true;
  return /\b(?:python3?|uv\s+run\s+python3?)\s+scripts\/opencode_response_media\.py\b/.test(value);
}

function validResponseMediaVideoSnippetForTest(snippet) {
  return /<source\b[^>]*\bsrc=(['"])https?:\/\/[^'"]+\1[^>]*>/i.test(String(snippet || ""));
}

function firstResponseMediaImageSnippetForTest(text) {
  const match = String(text || "").match(/!\[[^\]]*\]\(https?:\/\/[^\s)]+\)/i);
  return match ? match[0] : "";
}

function canonicalResponseMediaKeySourceForTest(value) {
  return String(value || "")
    .replace(/\\"/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

function existingPathCandidateForTest(candidate) {
  if (!candidate) return "";
  try {
    if (!existsSync(candidate)) return "";
    return realpathSync(candidate);
  } catch {
    return "";
  }
}

function resolveExistingFigmaExportPathForTest(
  figmaPath,
  { cwd = "", worktreePath = "", projectRoot = PROJECT_ROOT, controlPlaneRoot = CURRENT_CONTROL_PLANE_ROOT } = {},
) {
  const raw = String(figmaPath || "").trim();
  if (!raw || raw.includes("\0")) return "";
  const candidates = [];
  if (isAbsolute(raw)) {
    candidates.push(raw);
  } else {
    for (const base of [cwd, worktreePath, projectRoot, controlPlaneRoot, activeCwd()].filter(Boolean)) {
      candidates.push(resolve(base, raw));
    }
  }
  const seen = new Set();
  for (const candidate of candidates) {
    if (seen.has(candidate)) continue;
    seen.add(candidate);
    const existing = existingPathCandidateForTest(candidate);
    if (existing) return existing;
  }
  return "";
}

function responseMediaAutomationEnabledForTest(env = process.env) {
  return String(env?.OPENMATES_OPENCODE_RESPONSE_MEDIA_AUTOMATION || "").trim() === "1";
}

function responseMediaArtifactForTest({
  command = "",
  output = "",
  cwd = "",
  worktreePath = "",
  requireExistingFigmaExport = false,
  automationEnabled = responseMediaAutomationEnabledForTest(),
} = {}) {
  if (!automationEnabled) return null;
  const video = firstResponseMediaVideoSnippetForTest(output);
  if (
    video
    && responseMediaVideoProducerCommandForTest(command)
    && validResponseMediaVideoSnippetForTest(video)
  ) {
    const key = createHash("sha256").update(canonicalResponseMediaKeySourceForTest(video)).digest("hex").slice(0, 24);
    return { artifact_type: "video", artifact_key: key, snippet: video };
  }
  const combined = `${command}\n${output}`;
  const figmaPath = figmaExportPathForTest(combined);
  const resolvedFigmaPath = figmaPath
    ? resolveExistingFigmaExportPathForTest(figmaPath, { cwd, worktreePath })
    : "";
  const image = firstResponseMediaImageSnippetForTest(output);
  if (image && /figma/i.test(combined)) {
    const keySource = resolvedFigmaPath || figmaPath || image;
    const key = createHash("sha256").update(canonicalResponseMediaKeySourceForTest(keySource)).digest("hex").slice(0, 24);
    return { artifact_type: "figma_image", artifact_key: key, snippet: image };
  }
  if (figmaPath) {
    if (requireExistingFigmaExport && !resolvedFigmaPath) return null;
    const uploadPath = resolvedFigmaPath || figmaPath;
    const key = createHash("sha256").update(canonicalResponseMediaKeySourceForTest(uploadPath)).digest("hex").slice(0, 24);
    return {
      artifact_type: "figma_export",
      artifact_key: key,
      artifact_path: resolvedFigmaPath,
      snippet: `Figma export pending upload: ${uploadPath}`,
    };
  }
  return null;
}

function mediaDeliveryPromptForTest(record, { automationEnabled = responseMediaAutomationEnabledForTest() } = {}) {
  if (!automationEnabled) return "";
  if (!record?.snippet) return "";
  if (record.artifact_type === "figma_export") return "";
  const label = record.artifact_type === "video" ? "video" : "Figma reference";
  return `A required ${label} artifact from the previous tool result is still pending. Include this exact snippet in your next progress response, even when the result is visibly broken or further debugging remains:\n${record.snippet}\nDo not redo completed tests merely to regenerate it.`;
}

function responseContainsMediaForTest(text, record) {
  if (!record?.snippet) return false;
  const content = String(text || "");
  if (content.includes(record.snippet)) return true;
  if (record.artifact_type === "video") {
    return canonicalResponseMediaKeySourceForTest(content).includes(canonicalResponseMediaKeySourceForTest(record.snippet));
  }
  return false;
}

function figmaExportPathFromRecordForTest(record) {
  const explicit = String(record?.artifact_path || "").trim();
  if (explicit) return explicit;
  const snippet = String(record?.snippet || "");
  const pending = snippet.match(/^Figma export pending upload:\s*(.+)$/i);
  if (pending) return pending[1].trim();
  const legacy = snippet.match(/opencode_response_media\.py\s+([^\s]+\.png)\b/i);
  return legacy ? legacy[1] : "";
}

function assistantTextPartForTest(event) {
  if (event?.type !== "message.part.updated") return null;
  const part = event?.properties?.part;
  if (part?.type !== "text" || typeof part.text !== "string") return null;
  const messageID = part.messageID || part.message_id || event?.properties?.messageID || "";
  if (!messageID) return null;
  return { messageID, partID: part.id || "text", text: part.text };
}

function appendResponseMediaEmbedHint(command, output) {
  if (!responseMediaAutomationEnabledForTest()) return;
  if (!output || typeof output.output !== "string" || output.output.includes(RESPONSE_MEDIA_EMBED_MARKER)) return;
  if (!/scripts\/(?:tests\.py\s+run|cli_video_capture\.py)\b/.test(command)) return;
  const snippet = firstResponseMediaVideoSnippetForTest(output.output);
  if (!snippet) return;
  output.output += `

${RESPONSE_MEDIA_EMBED_MARKER}
This E2E run generated an OpenCode response-media video. Paste this exact <video> HTML in the next assistant progress response, even if the run/proof is still broken or still being debugged:
${snippet}`;
}

function figmaExportPathForTest(text) {
  const match = String(text || "").match(/(?:^|[\s"'])(\.?\/?(?:[\w.-]+\/)*test-results\/figma\/[^\s"'<>]+\.png)\b/i);
  return match ? match[1] : "";
}

function appendFigmaReferenceEmbedHint({ tool = "", command = "", cwd = "", worktreePath = "" } = {}, output) {
  if (!responseMediaAutomationEnabledForTest()) return;
  if (!output || typeof output.output !== "string" || output.output.includes(FIGMA_REFERENCE_EMBED_MARKER)) return;
  const value = `${tool} ${command} ${output.output}`;
  if (!/figma/i.test(value)) return;
  if (!/download_figma_images|test-results\/figma\/[^\s"'<>]+\.png|figma-[^\s"'<>]+\.png/i.test(value)) return;
  const exportPath = figmaExportPathForTest(output.output);
  const resolvedPath = exportPath ? resolveExistingFigmaExportPathForTest(exportPath, { cwd, worktreePath }) : "";
  const pathHint = exportPath ? `\nDetected reference export: ${exportPath}` : "";
  const deliveryHint = exportPath && !resolvedPath
    ? `\nAutomatic response-media delivery was not queued because the PNG was not found from this session's routed checkout. Re-run the Figma export in the active worktree before reporting implementation progress for that frame.`
    : "";
  output.output += `

${FIGMA_REFERENCE_EMBED_MARKER}
For Figma-based UI work, embed the exported Figma screenshot for the screen/frame currently being implemented in the next assistant progress response, and repeat when switching target frames. Upload it with:
  python3 scripts/opencode_response_media.py <exported-figma-png> --alt "Figma reference: <screen/frame>"
Then paste the returned image Markdown before summarizing implementation progress.${pathHint}${deliveryHint}`;
}

function continuationSignalForTest(text) {
  for (const line of String(text || "").split(/\r?\n/)) {
    if (!line.includes("OPENMATES_") || !line.trim().startsWith("{")) continue;
    try {
      const payload = JSON.parse(line);
      if (
        ["OPENMATES_WAIT_READY", "OPENMATES_HEALTH_READY", "OPENMATES_CONTINUATION_READY"].includes(payload.signal)
        && payload.operation_type
        && payload.operation_key
        && payload.next_action
      ) return payload;
    } catch {
      // Only typed JSON signal lines are continuation records.
    }
  }
  return null;
}

function continuationSuppressedForTest(state) {
  return Boolean(
    ["aborted", "failed"].includes(state?.turn)
    || ["stopped", "error", "closed"].includes(state?.execution)
    || (state?.pending_permission_ids || []).length
    || (state?.pending_question_ids || []).length
  );
}

function taskBridgeSuppressedForTest(state) {
  return continuationSuppressedForTest(state) || state?.execution !== "idle";
}

function taskBridgeCompletionForTest(event, { topLevelSessionID = "" } = {}) {
  const messageID = completedAssistantMessageID(event);
  const sessionID = eventSessionID(event);
  if (!messageID || !sessionID || !topLevelSessionID || sessionID !== topLevelSessionID) return null;
  return { sessionID, messageID };
}

function taskContextSystemTextForTest(snapshot) {
  if (!snapshot || snapshot.decision === "unbound") return "";
  const active = snapshot.active;
  const remaining = Array.isArray(snapshot.remaining) ? snapshot.remaining : [];
  const lines = [
    TASK_CONTEXT_MARKER,
    "This request-only snapshot is authoritative. Use the openmates_task tool for Task mutations; native OpenCode todos are unavailable.",
  ];
  if (active) {
    lines.push(
      "Active Task:",
      `- ID: ${active.task_id || ""}`,
      `- Short ID: ${active.short_id || ""}`,
      `- Title: ${active.title || ""}`,
      `- Status: ${active.status || ""}`,
      `- Version: ${active.version ?? ""}`,
      `- Description: ${active.description || ""}`,
      `- Latest instruction: ${active.latest_instruction || ""}`,
    );
    if (active.blocked_reason_code) lines.push(`- Blocked reason code: ${active.blocked_reason_code}`);
    if (active.blocked_reason) lines.push(`- Blocked explanation: ${active.blocked_reason}`);
  } else {
    lines.push(
      "Active Task: none",
      "For non-trivial multi-step implementation, debugging, or investigation work, create an AI-assigned record with openmates_task action=create before the first product mutation, even when the user did not explicitly mention Tasks or todos.",
      "After creating it, carry out the work and explicitly mark it done or block it with an allowlisted reason before ending the response.",
      "For simple informational requests or trivial single-action work, do not create a record.",
    );
  }
  lines.push("Ordered remaining Tasks (short id, title, status only):");
  if (remaining.length === 0) lines.push("- none");
  else {
    for (const task of remaining) {
      lines.push(`- ${task.short_id || ""} | ${task.title || ""} | ${task.status || ""}`);
    }
  }
  lines.push(
    "Before ending work, explicitly mark the active Task done or block it with an allowlisted reason. Do not infer Task state from prose.",
  );
  return lines.join("\n");
}

function implicitTaskMutationPayloadForTest(snapshot, { tool = "", command = "", sessionTitle = "" } = {}) {
  if (!snapshot || snapshot.active || (Array.isArray(snapshot.remaining) && snapshot.remaining.length > 0)) return null;
  // Repository source writes are required to use routed edit tools; mutating
  // Bash is separately guarded and may legitimately write only temporary data.
  if (!EDIT_TOOLS.has(tool)) return null;
  const title = String(sessionTitle || "Complete requested OpenCode work").trim().slice(0, 500)
    || "Complete requested OpenCode work";
  return {
    action: "create",
    title,
    description: "Automatically created before the first repository mutation in this OpenCode chat.",
    status: "in_progress",
  };
}

function taskContinuationPromptForTest(record) {
  if (record?.operation_type !== "task_ready") return String(record?.next_action || "");
  return String(record.next_action || "Continue the active OpenMates Task from request-only context.");
}

async function runTaskBridgeCommand(action, sessionID, { messageID = "", payload = null } = {}) {
  const args = ["scripts/sessions.py", "task-bridge", action, "--session", sessionID];
  if (action === "stage") args.push("--message-id", messageID);
  if (action === "tool") args.push("--json-stdin");
  const result = await runProcess("python3", args, {
    cwd: CURRENT_CONTROL_PLANE_ROOT,
    input: action === "tool" ? JSON.stringify(payload || {}) : "",
  });
  if (result.status !== 0) throw new Error(result.stderr || result.stdout || `task-bridge ${action} failed`);
  return JSON.parse(result.stdout || "{}").task_bridge || null;
}

function reconcilePresenceStatesForTest(
  states,
  authoritativeStatuses,
  { now = isoNow(), authoritativePending = null } = {},
) {
  const reconciled = [];
  for (const originalState of states) {
    const state = authoritativePending
      ? {
          ...originalState,
          pending_permission_ids: authoritativePending.permissionIDs instanceof Set
            ? (originalState.pending_permission_ids || []).filter((id) => authoritativePending.permissionIDs.has(id))
            : (originalState.pending_permission_ids || []),
          pending_question_ids: authoritativePending.questionIDs instanceof Set
            ? (originalState.pending_question_ids || []).filter((id) => authoritativePending.questionIDs.has(id))
            : (originalState.pending_question_ids || []),
        }
      : originalState;
    if (authoritativePending) state.attention = attentionFromPending(state);
    if (!PRESENCE_LIVE_EXECUTION.has(state?.execution) && state?.turn !== "streaming") continue;
    const status = authoritativeStatuses?.[state.session_id];
    const type = status?.type || status?.status?.type || "idle";
    if (type === "busy" || type === "retry") {
      reconciled.push({
        ...state,
        execution: type === "retry" ? "retrying" : "busy",
        heartbeat_at: now,
        updated_at: now,
      });
      continue;
    }
    const activityAt = Date.parse(state.heartbeat_at || state.updated_at || "");
    const snapshotAt = Date.parse(now);
    if (
      !status
      && Number.isFinite(activityAt)
      && Number.isFinite(snapshotAt)
      && snapshotAt - activityAt >= -1_000
      && snapshotAt - activityAt < PRESENCE_ABSENT_STATUS_GRACE_MS
    ) {
      // A status request can start just before a generation event and finish
      // just after it. Do not let that older absent snapshot erase fresh tool
      // or streaming activity; the next 30s reconciliation clears real stale
      // state if OpenCode still reports no generation.
      continue;
    }
    const idle = { ...state, execution: "idle", updated_at: now };
    if (idle.turn === "streaming") idle.turn = "none";
    idle.attention = attentionFromPending(idle);
    reconciled.push(idle);
  }
  return reconciled;
}

function activeCwd() {
  return process.cwd() || PROJECT_ROOT;
}

function runProcess(command, args, {
  cwd = PROJECT_ROOT,
  env = process.env,
  input = "",
  timeoutMs = HOOK_SUBPROCESS_TIMEOUT_MS,
} = {}) {
  return new Promise((resolvePromise) => {
    const child = spawn(command, args, { cwd, env, stdio: ["pipe", "pipe", "pipe"] });
    const stdout = [];
    const stderr = [];
    const timeout = timeoutMs > 0
      ? setTimeout(() => {
        child.kill("SIGTERM");
        finish(null, `timed out after ${timeoutMs}ms`);
      }, timeoutMs)
      : null;
    let settled = false;
    const finish = (status, error = "") => {
      if (settled) return;
      settled = true;
      if (timeout) clearTimeout(timeout);
      resolvePromise({
        status,
        stdout: Buffer.concat(stdout).toString(),
        stderr: `${Buffer.concat(stderr).toString()}${error}`,
      });
    };
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    child.on("error", (error) => finish(null, error.message));
    child.on("close", (code) => finish(code));
    child.stdin.end(input);
  });
}

async function sessionsCommandSupportedForTest(command, run = runProcess) {
  if (!/^[a-z][a-z0-9-]*$/.test(String(command || ""))) return false;
  const result = await run(
    "python3",
    ["scripts/sessions.py", command, "--help"],
    { cwd: CURRENT_CONTROL_PLANE_ROOT, timeoutMs: 10_000 },
  );
  return result.status === 0;
}

async function runBridge(event, payload, sessionID, cwd = activeCwd()) {
  const result = await runProcess("bash", [BRIDGE, event], {
    cwd,
    env: sessionID ? { ...process.env, OPENCODE_SESSION_ID: sessionID } : process.env,
    input: JSON.stringify(payload),
  });
  const stdout = (result.stdout || "").trim();
  const stderr = (result.stderr || "").trim();
  if (stdout) console.log(stdout);
  if (stderr) console.error(stderr);
  if (result.status !== 0) {
    const detail = stderr || stdout || `shared hook exited ${result.status}`;
    throw new Error(actionable("[OpenMates shared hook guard]", detail, "follow the guard detail above, then retry the permitted alternative once."));
  }
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
  const target = worktreePath ? ` The routed worktree is ${worktreePath}.` : "";
  return actionable(
    ROOT_GUARD_MARKER,
    `the target is in the root control-plane checkout.${target}`,
    `use a repository-relative path; if the user explicitly needs existing root-dirty work, list it with python3 scripts/sessions.py worktree root-dirty and import only an exact reviewed file with python3 scripts/sessions.py worktree import-root --session ${sessionID || "<id>"} --file <path>; if routing is missing, run python3 scripts/sessions.py worktree ensure --session ${sessionID || "<id>"}.`,
  );
}

function rootGuardDecisionForTest({ mode = "strict", cwd = PROJECT_ROOT, target = "", sessionID = "", opencodeSessionID = "", sessions = null, worktreePath = "" } = {}) {
  const normalized = String(mode || "strict").toLowerCase();
  if (["off", "0", "false"].includes(normalized)) return { decision: "allow", message: "root guard disabled" };
  if (!isInsideProjectRoot(target) || isInsideAgentWorktree(cwd, target)) return { decision: "allow", message: "target is not a root checkout source edit" };
  const mappedSessionID = opencodeSessionID ? activeSessionRecord(opencodeSessionID, sessions || sessionsData())?.id : "";
  const message = worktreeGuardMessage(sessionID || mappedSessionID, worktreePath);
  if (worktreePath) return { decision: "block", message };
  return { decision: normalized === "strict" ? "block" : "warn", message };
}

function normalizedGuardPathForTest(value, cwd = activeCwd()) {
  const raw = String(value || "").replaceAll("\\", "/");
  if (!raw) return "";
  const absolute = isAbsolute(raw) ? resolve(raw) : resolve(cwd, raw);
  const normalized = absolute.replaceAll("\\", "/");
  const rootRelative = relative(PROJECT_ROOT, absolute).replaceAll("\\", "/");
  if (rootRelative && !rootRelative.startsWith("../") && rootRelative !== "..") return rootRelative;
  for (const root of WORKTREE_ROOTS) {
    const prefix = `${root.replace(/\/$/, "")}/`;
    if (!normalized.startsWith(prefix)) continue;
    const worktreeRelative = normalized.slice(prefix.length).split("/").slice(1).join("/");
    if (worktreeRelative) return worktreeRelative;
  }
  return normalized;
}

function protectedControlPlanePathForTest(value, cwd = activeCwd()) {
  const normalized = normalizedGuardPathForTest(value, cwd).replace(/^\.\//, "");
  return PROTECTED_CONTROL_PLANE_PATHS.some((protectedPath) => (
    protectedPath.endsWith("/") || protectedPath.endsWith("-")
      ? normalized.startsWith(protectedPath)
      : normalized === protectedPath
  ));
}

function secretConfigPathForTest(value, cwd = activeCwd()) {
  const normalized = (isAbsolute(String(value || "")) ? resolve(String(value)) : resolve(cwd, String(value || "")))
    .replaceAll("\\", "/");
  return SECRET_CONFIG_PATHS.some((protectedPath) => (
    protectedPath.endsWith("/") ? normalized.startsWith(protectedPath) : normalized === protectedPath
  ));
}

function commandReferencesProtectedControlPlaneForTest(command) {
  const value = String(command || "").replaceAll("\\", "/");
  return /(?:^|[\s'"/])(?:\.opencode\/|backend\/engineering_control_plane\/|opencode\.json\b|scripts\/(?:sessions\.py\b|server-restart\.sh\b|start-opencode-server\.sh\b|sync_opencode_runtime_hook\.py\b|opencode_(?:permission_watcher|credential_migration|runtime_release)\.py\b|patches\/opencode-))/.test(value);
}

function commandReferencesSecretConfigForTest(command) {
  const value = String(command || "").replaceAll("\\", "/");
  return /(?:\/home\/superdev|\$HOME|\$\{HOME\}|~)?\/?(?:\.config\/opencode(?:\/|\b)|opencode\/\.opencode\/opencode\.jsonc\b)|\bsecrets\.env\b/.test(value);
}

function commandMutatesFilesForTest(command) {
  const value = String(command || "");
  return /(?:^|[;&|]\s*|\s)(?:apply_patch|chmod|chown|cp|install|mv|perl\s+-[^\n]*i|rm|sed\s+-[^\n]*i|tee|truncate)(?:\s|$)|(?:^|[^<])>{1,2}(?!>)/.test(value);
}

function directSessionsSpawnChatCommandForTest(command) {
  const args = directPythonScriptArgs(String(command || ""));
  return Boolean(args && args[0] === "scripts/sessions.py" && args[1] === "spawn-chat");
}

function controlPlaneToolDecisionForTest({ tool = "", args = {}, cwd = activeCwd() } = {}) {
  const files = EDIT_TOOLS.has(tool)
    ? editedFilesForTest(args, cwd)
    : explicitFilesForTest(args, cwd);
  if ((READ_TOOLS.has(tool) || SEARCH_TOOLS.has(tool) || EDIT_TOOLS.has(tool)) && files.some((file) => secretConfigPathForTest(file, cwd))) {
    return {
      decision: "block",
      message: actionable(CONTROL_PLANE_GUARD_MARKER, "OpenCode credential configuration is outside the product-agent trust boundary.", "use the dedicated Codex control-plane workflow; do not expose or copy credential values."),
    };
  }
  if (EDIT_TOOLS.has(tool) && files.some((file) => protectedControlPlanePathForTest(file, cwd))) {
    return {
      decision: "block",
      message: actionable(CONTROL_PLANE_GUARD_MARKER, "ordinary product chats cannot edit shared OpenCode or sessions.py orchestration files.", "preserve the product worktree and move this control-plane change to the dedicated Codex recovery branch."),
    };
  }
  if (BASH_TOOLS.has(tool)) {
    const command = bashCommand(args);
    // spawn-chat receives a quoted prompt as opaque data. Inspecting that
    // payload as shell syntax creates false positives when the handoff names a
    // protected path or embeds HTML such as `<audio controls>`. Only exempt a
    // single, directly parsed sessions.py invocation; chained shell commands,
    // substitutions, and redirections still fail directPythonScriptArgs().
    if (directSessionsSpawnChatCommandForTest(command)) {
      return { decision: "allow", message: "canonical spawn-chat prompt is opaque data" };
    }
    if (commandReferencesSecretConfigForTest(command)) {
      return {
        decision: "block",
        message: actionable(CONTROL_PLANE_GUARD_MARKER, "shell access to OpenCode credential configuration is forbidden.", "use the dedicated Codex control-plane workflow without printing credential values."),
      };
    }
    if (commandReferencesProtectedControlPlaneForTest(command) && commandMutatesFilesForTest(command)) {
      return {
        decision: "block",
        message: actionable(CONTROL_PLANE_GUARD_MARKER, "the shell command would mutate shared OpenCode or sessions.py orchestration files.", "move this change to the dedicated Codex recovery branch."),
      };
    }
  }
  return { decision: "allow", message: "" };
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
    if (decision.decision === "warn") warnOnceForTest(decision.message, { sessionID });
  }
}

function editedFilesForTest(args, cwd = activeCwd()) {
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

function editedFilesForBindingForTest(args, binding = {}) {
  return editedFilesForTest(args, binding.worktreePath || activeCwd());
}

function explicitFilesForTest(args, cwd = activeCwd()) {
  const input = toolInput(args);
  const explicit = input.file_path || input.filePath || input.path;
  return explicit ? [toAbsPath(explicit, cwd)] : [];
}

async function runStaleRead(action, files, sessionID) {
  if (!sessionID) return;
  for (const file of files) {
    const result = await runProcess("python3", ["scripts/sessions.py", "stale-read", action, "--opencode-session", sessionID, "--file", file], {
      cwd: PROJECT_ROOT,
    });
    const stdout = (result.stdout || "").trim();
    const stderr = (result.stderr || "").trim();
    if (stdout) console.log(stdout);
    if (stderr) console.error(stderr);
    if (result.status === 2) {
      const detail = stderr || stdout || "the file changed since it was read";
      throw new Error(actionable("[OpenMates stale-read guard]", detail, `re-read ${file}, reapply the intended change to the latest content, then retry once.`));
    }
  }
}

async function runEditLease(action, files, sessionID) {
  if (!sessionID || !files.length) return;
  const result = await runProcess("python3", ["scripts/sessions.py", "edit-lease", action, "--opencode-session", sessionID, "--file", ...files], {
    cwd: PROJECT_ROOT,
  });
  const stdout = (result.stdout || "").trim();
  const stderr = (result.stderr || "").trim();
  if (stdout) console.log(stdout);
  if (stderr) console.error(stderr);
  if (result.status === 2) {
    const detail = stderr || stdout || "another live session holds an overlapping edit lease";
    throw new Error(actionable("[OpenMates edit lease guard]", detail, "re-read the file after the current lease releases, then retry once."));
  }
  if (result.status !== 0) {
    const detail = stderr || stdout || `edit lease command exited ${result.status}`;
    throw new Error(actionable("[OpenMates edit lease guard]", detail, "run python3 scripts/sessions.py status, resolve the reported session-state error, then retry."));
  }
}

function workerEditGateDecisionForTest({ sessionID = "", files = [], run = spawnSync } = {}) {
  const selectedFiles = (files || []).filter(Boolean);
  if (!sessionID || selectedFiles.length === 0) return { decision: "allow", message: "no worker edit gate input" };
  const args = ["scripts/tests.py", "campaign", "edit-gate", "--session", sessionID];
  for (const file of selectedFiles) args.push("--file", file);
  const result = run("python3", args, { cwd: PROJECT_ROOT, encoding: "utf8", timeout: 10000 });
  if (result.status === 0) return { decision: "allow", message: "worker edit gate passed" };
  const detail = (result.stderr || result.stdout || `worker edit gate exited ${result.status}`).trim();
  return {
    decision: "block",
    message: actionable(
      "[OpenMates worker edit gate]",
      detail,
      "submit `campaign intent`, wait for coordinator `approve-intent`, then edit only files in the approved write set.",
    ),
  };
}

function workerEditPathDecisionForTest({ sessionID = "", files = [], relativePaths = [], run = spawnSync } = {}) {
  if (!sessionID || !(files || []).length) return { decision: "allow", message: "no worker edit paths" };
  if ((relativePaths || []).length === (files || []).length) return { decision: "allow", message: "all edit paths resolved" };
  const state = workerSessionStateForTest({ sessionID, run });
  if (!state?.active_worker) return { decision: "allow", message: "session is not an active debug worker" };
  return {
    decision: "block",
    message: actionable(
      "[OpenMates worker edit gate]",
      "active debug workers may edit only paths that resolve inside the repository or assigned worktree.",
      "retry with repository-relative paths inside the approved write set.",
    ),
  };
}

async function guardWorkerEditPaths(files, relativePaths, sessionID) {
  if (!sessionID || !files.length || relativePaths.length === files.length) return;
  const state = await workerSessionState(sessionID);
  if (!state?.active_worker) return;
  throw new Error(actionable(
    "[OpenMates worker edit gate]",
    "active debug workers may edit only paths that resolve inside the repository or assigned worktree.",
    "retry with repository-relative paths inside the approved write set.",
  ));
}

async function guardWorkerEditGate(files, sessionID) {
  if (!sessionID || !files.length) return;
  const args = ["scripts/tests.py", "campaign", "edit-gate", "--session", sessionID];
  for (const file of files) args.push("--file", file);
  const result = await runProcess("python3", args);
  if (result.status === 0) return;
  const detail = (result.stderr || result.stdout || `worker edit gate exited ${result.status}`).trim();
  throw new Error(actionable(
    "[OpenMates worker edit gate]",
    detail,
    "submit `campaign intent`, wait for coordinator `approve-intent`, then edit only files in the approved write set.",
  ));
}

function workerCampaignCommandIsAllowed(command) {
  if (hasUnsafeLocalShellExpansionOrRedirection(command)) return false;
  const segments = commandSegmentTokens(command.replace(/\\\s*\n/g, " "));
  if (segments.length !== 1) return false;
  if (changesOpenCodeSessionEnvironment(segments[0])) return false;
  const invocation = normalizedInvocation(segments[0]);
  if (!["python", "python3"].includes(invocation.command)) return false;
  const script = shellUnescape(invocation.args[0] || "").replace(/^\.\//, "");
  if (script !== "scripts/tests.py") return false;
  const args = invocation.args.slice(1).map(shellUnescape);
  if (args[0] === "lease-required") return true;
  if (args[0] !== "campaign") return false;
  return new Set(["status", "prepare", "intent", "attempt", "boundary", "finish-worker", "worker-state"]).has(args[1]);
}

function workerCampaignCommandSpoofsSession(command) {
  const commandText = String(command || "");
  const mutatingVerb = mutatingCampaignVerbFromText(commandText);
  if (mutatingVerb) {
    if (hasUnsafeLocalShellExpansionOrRedirection(commandText)) return true;
    if (/\bOPENCODE_SESSION_ID\b/.test(commandText)) return true;
    if (/\b(?:bash|sh|python3?|node)\s+-c\b/.test(commandText)) return true;
  }
  const segments = commandSegmentTokens(command.replace(/\\\s*\n/g, " "));
  let sessionEnvironmentChanged = false;
  for (const segment of segments) {
    if (hasOpenCodeSessionEnvironmentChange(segment)) sessionEnvironmentChanged = true;
    const verb = testsCampaignVerbFromTokens(segment);
    if (sessionEnvironmentChanged && verb && !new Set(["status", "worker-state"]).has(verb)) return true;
  }
  return false;
}

function interpreterEvaluationCommand(command) {
  const segments = commandSegmentTokens(String(command || "").replace(/\\\s*\n/g, " "));
  if (segments.length !== 1) return false;
  const invocation = normalizedInvocation(segments[0]);
  const args = invocation.args.map(shellUnescape);
  if (["bash", "sh"].includes(invocation.command)) return args.includes("-c") || args.includes("--command");
  if (["python", "python3"].includes(invocation.command)) return args.includes("-c");
  if (invocation.command === "node") return args.includes("-e") || args.includes("--eval") || args.includes("-p") || args.includes("--print");
  return false;
}

function workerSessionStartCommandIsAllowed(command, sessionID = "") {
  if (hasUnsafeLocalShellExpansionOrRedirection(command)) return false;
  const segments = commandSegmentTokens(command.replace(/\\\s*\n/g, " "));
  if (segments.length !== 1) return false;
  if (changesOpenCodeSessionEnvironment(segments[0])) return false;
  const invocation = normalizedInvocation(segments[0]);
  if (!["python", "python3"].includes(invocation.command)) return false;
  const script = shellUnescape(invocation.args[0] || "").replace(/^\.\//, "");
  const args = invocation.args.slice(1).map(shellUnescape);
  if (script !== "scripts/sessions.py" || args[0] !== "start") return false;
  const sessionIndex = args.indexOf("--opencode-session");
  if (sessionIndex < 0 || sessionIndex + 1 >= args.length) return false;
  return new Set([sessionID, "$OPENCODE_SESSION_ID", "${OPENCODE_SESSION_ID}"]).has(args[sessionIndex + 1]);
}

function workerServerRecoveryCommandIsAllowed(command) {
  if (hasUnsafeLocalShellExpansionOrRedirection(command)) return false;
  const segments = commandSegmentTokens(command.replace(/\\\s*\n/g, " "));
  if (segments.length !== 1) return false;
  const tokens = segments[0].map(shellUnescape);
  if (basename(tokens[0] || "") !== "openmates") return false;
  const args = tokens.slice(1);
  if (args.length === 2 && args[0] === "server" && args[1] === "status") return true;
  if (args.length === 4
    && args[0] === "server"
    && args[1] === "restart"
    && args[2] === "--services"
    && args[3] === "cms") return true;
  if (args.length === 5
    && args[0] === "server"
    && args[1] === "restart"
    && args[2] === "--rebuild"
    && args[3] === "--services"
    && args[4] === "cms") return true;
  return args.length === 5
    && args[0] === "server"
    && args[1] === "start"
    && args[2] === "--with-overrides"
    && args[3] === "--services"
    && args[4] === "cms";
}

function invocationRunsOpenMatesCli(tokens, depth = 0) {
  const invocation = normalizedInvocation(tokens.map(shellUnescape));
  let { command, args } = invocation;
  while (["command", "builtin"].includes(command) && args.length) {
    command = basename(args[0]);
    args = args.slice(1);
  }
  if (command === "exec" && args.length) {
    return invocationRunsOpenMatesCli(args, depth);
  }
  if (command === "openmates") return true;
  if (["npx", "bunx", "pnpm", "yarn"].includes(command) && args.some((arg) => basename(arg) === "openmates")) return true;
  if (command === "node" && args.some((arg) => /(?:^|\/)openmates-cli\/(?:dist\/)?cli\.js$/.test(arg) || /(?:^|\/)dist\/cli\.js$/.test(arg))) return true;
  if (depth < 2 && command === "eval" && args.length) {
    return commandSegmentTokens(args.join(" ")).some((segment) => invocationRunsOpenMatesCli(segment, depth + 1));
  }
  if (depth < 2 && ["bash", "sh"].includes(command)) {
    const evaluationIndex = args.findIndex((arg) => arg === "--command" || /^-[^-]*c/.test(arg));
    if (evaluationIndex >= 0 && args[evaluationIndex + 1]) {
      return commandSegmentTokens(args[evaluationIndex + 1]).some((segment) => invocationRunsOpenMatesCli(segment, depth + 1));
    }
  }
  return false;
}

const PROTECTED_OPENMATES_ENVIRONMENT = new Set([
  "OPENMATES_PROFILE",
  "OPENMATES_ACCOUNT_GUARD",
  "OPENMATES_API_URL",
  "OPENMATES_STATE_DIR",
]);

function protectedOpenMatesAssignment(token) {
  const match = String(token || "").match(/^([A-Za-z_][A-Za-z0-9_]*)(?:\+?=|:=)/);
  return Boolean(match && PROTECTED_OPENMATES_ENVIRONMENT.has(match[1]));
}

function mutatesProtectedOpenMatesEnvironment(tokens, depth = 0) {
  const args = tokens.map(shellUnescape);
  let index = 0;
  while (index < args.length && (isAssignment(args[index]) || protectedOpenMatesAssignment(args[index]))) {
    if (protectedOpenMatesAssignment(args[index])) return true;
    index += 1;
  }
  if (index >= args.length) return false;

  let command = basename(args[index]);
  let commandArgs = args.slice(index + 1);
  while (["command", "builtin"].includes(command) && commandArgs.length) {
    command = basename(commandArgs[0]);
    commandArgs = commandArgs.slice(1);
  }
  if (command === "exec") return mutatesProtectedOpenMatesEnvironment(commandArgs, depth);

  if (["export", "readonly", "declare", "typeset"].includes(command)) {
    if (command === "export" && commandArgs.includes("-n")) {
      return commandArgs.some((arg) => PROTECTED_OPENMATES_ENVIRONMENT.has(arg));
    }
    return commandArgs.some(protectedOpenMatesAssignment);
  }
  if (command === "unset") {
    return commandArgs.some((arg) => PROTECTED_OPENMATES_ENVIRONMENT.has(arg));
  }
  if (command === "env") {
    let resetsEnvironment = false;
    let envIndex = 0;
    while (envIndex < commandArgs.length) {
      const arg = commandArgs[envIndex];
      if (arg === "--") {
        envIndex += 1;
        break;
      }
      if (protectedOpenMatesAssignment(arg)) return true;
      if (arg === "-i" || arg === "--ignore-environment") {
        resetsEnvironment = true;
        envIndex += 1;
        continue;
      }
      if (arg === "-u" || arg === "--unset") {
        if (PROTECTED_OPENMATES_ENVIRONMENT.has(commandArgs[envIndex + 1])) return true;
        envIndex += 2;
        continue;
      }
      if (arg.startsWith("--unset=")) {
        if (PROTECTED_OPENMATES_ENVIRONMENT.has(arg.slice("--unset=".length))) return true;
        envIndex += 1;
        continue;
      }
      if (["-C", "--chdir", "-S", "--split-string"].includes(arg)) {
        envIndex += 2;
        continue;
      }
      if (isAssignment(arg) || isOption(arg)) {
        envIndex += 1;
        continue;
      }
      break;
    }
    const nested = commandArgs.slice(envIndex);
    if (resetsEnvironment && invocationRunsOpenMatesCli(nested, depth + 1)) return true;
    return depth < 2 && nested.length
      ? mutatesProtectedOpenMatesEnvironment(nested, depth + 1)
      : false;
  }
  if (depth < 2 && command === "eval" && commandArgs.length) {
    return commandSegmentTokens(commandArgs.join(" "))
      .some((segment) => mutatesProtectedOpenMatesEnvironment(segment, depth + 1));
  }
  if (depth < 2 && ["bash", "sh"].includes(command)) {
    const evaluationIndex = commandArgs.findIndex((arg) => arg === "--command" || /^-[^-]*c/.test(arg));
    if (evaluationIndex >= 0 && commandArgs[evaluationIndex + 1]) {
      return commandSegmentTokens(commandArgs[evaluationIndex + 1])
        .some((segment) => mutatesProtectedOpenMatesEnvironment(segment, depth + 1));
    }
  }
  return false;
}

function openMatesCliIsolationDecisionForTest(command = "") {
  const text = String(command);
  const segments = commandSegmentTokens(text.replace(/\\\s*\n/g, " "));
  const protectedEnvironmentOverride = segments
    .some((segment) => mutatesProtectedOpenMatesEnvironment(segment));
  const invokesCli = segments.some((segment) => invocationRunsOpenMatesCli(segment));
  if (!protectedEnvironmentOverride && !invokesCli) return { decision: "allow", message: "not an OpenMates CLI command" };
  if (protectedEnvironmentOverride || (invokesCli && /(?:^|\s)--api-url(?:=|\s|$)/.test(text))) {
    return {
      decision: "block",
      message: actionable(
        "[OpenMates CLI isolation]",
        "OpenCode CLI commands may not override or remove the trusted profile, account guard, state directory, or dev API endpoint.",
        "run the openmates command directly without OPENMATES_* overrides, env resets, or --api-url.",
      ),
    };
  }
  return { decision: "allow", message: "trusted OpenMates CLI environment preserved" };
}

function workerSessionStateForTest({ sessionID = "", run = spawnSync } = {}) {
  if (!sessionID) return { active_worker: false };
  const result = run("python3", ["scripts/tests.py", "campaign", "worker-state", "--session", sessionID], { cwd: PROJECT_ROOT, encoding: "utf8" });
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || `worker-state exited ${result.status}`).trim();
    throw new Error(actionable("[OpenMates worker edit gate]", detail, "resolve the test-control-plane worker-state error, then retry."));
  }
  try {
    return JSON.parse(result.stdout || "{}");
  } catch {
    throw new Error(actionable("[OpenMates worker edit gate]", "worker-state returned invalid JSON", "run python3 scripts/tests.py campaign worker-state --session <id> manually and fix the reported issue."));
  }
}

function workerBashGateDecisionForTest({ sessionID = "", command = "", run = spawnSync } = {}) {
  if (!sessionID || !command) return { decision: "allow", message: "no worker bash gate input" };
  if (workerCampaignCommandSpoofsSession(command)) {
    return {
      decision: "block",
      message: actionable(
        "[OpenMates worker edit gate]",
        "campaign worker lifecycle commands must not override OPENCODE_SESSION_ID.",
        "run the campaign command directly from the worker chat so the hook-provided session identity is preserved.",
      ),
    };
  }
  if (interpreterEvaluationCommand(command)) {
    return {
      decision: "block",
      message: actionable(
        "[OpenMates worker edit gate]",
        "nested interpreter evaluation is blocked because it can synthesize campaign commands with forged session identity.",
        "run direct scripts with explicit arguments instead of bash -c, sh -c, python -c, or node -e.",
      ),
    };
  }
  if (isReadOnlyChildBash(command) || workerCampaignCommandIsAllowed(command) || workerSessionStartCommandIsAllowed(command, sessionID)) return { decision: "allow", message: "worker bash command is read-only or campaign bookkeeping" };
  if (workerServerRecoveryCommandIsAllowed(command)) return { decision: "allow", message: "worker bash command is an approved CMS control-plane recovery command" };
  const state = workerSessionStateForTest({ sessionID, run });
  if (!state?.active_worker) return { decision: "allow", message: "session is not an active debug worker" };
  return {
    decision: "block",
    message: actionable(
      "[OpenMates worker edit gate]",
      "active debug workers may not run arbitrary mutating Bash commands because they bypass approved write-set checks.",
      "use read-only Bash for investigation, `campaign intent`/`boundary`/`finish-worker` for bookkeeping, and apply_patch/Edit after coordinator approval for source changes.",
    ),
  };
}

async function workerSessionState(sessionID) {
  if (!sessionID) return { active_worker: false };
  const result = await runProcess("python3", ["scripts/tests.py", "campaign", "worker-state", "--session", sessionID]);
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || `worker-state exited ${result.status}`).trim();
    throw new Error(actionable("[OpenMates worker edit gate]", detail, "resolve the test-control-plane worker-state error, then retry."));
  }
  try {
    return JSON.parse(result.stdout || "{}");
  } catch {
    throw new Error(actionable("[OpenMates worker edit gate]", "worker-state returned invalid JSON", "run python3 scripts/tests.py campaign worker-state --session <id> manually and fix the reported issue."));
  }
}

async function guardWorkerBashGate(command, sessionID) {
  const staticDecision = workerBashGateDecisionForTest({
    sessionID,
    command,
    run: () => ({ status: 0, stdout: '{"active_worker":false}' }),
  });
  if (staticDecision.decision === "block") throw new Error(staticDecision.message);
  if (staticDecision.message !== "session is not an active debug worker") return;
  const state = await workerSessionState(sessionID);
  if (!state?.active_worker) return;
  throw new Error(actionable(
    "[OpenMates worker edit gate]",
    "active failed-test workers may not run arbitrary shell commands outside the coordinator-approved campaign protocol.",
    "use read-only inspection or the approved tests.py campaign commands, or ask the coordinator to perform the mutation.",
  ));
}

export const OpenMatesHooks = async ({
  client,
  directory,
  routingData,
  recordRouting = true,
  editLease = runEditLease,
  taskBridge = runTaskBridgeCommand,
} = {}) => {
  const instanceDirectory = directory || activeCwd();
  const recordedRoutes = new Set();
  const presenceStates = new Map();
  const notifierLiveSessions = new Set();
  const routingBlockCounts = new Map();
  const sourceGenerations = new Map();
  const reviewedGenerations = new Map();
  const readyContinuationSessions = new Set();
  const taskContextCache = new Map();
  // OpenCode emits session.idle while a synchronous prompt submission is
  // unwinding. Keep delivery single-flight per session even if an SDK or
  // transport regression makes prompt_async behave synchronously again.
  const automaticDeliverySessions = new Set();
  const recordedChildRoles = new Set();
  const pendingMediaBySession = new Map();
  const claimedMediaBySession = new Map();
  // Queue automation and sessions.py are deployed independently. Feature-gate
  // each optional queue by executing its help command once; unsupported
  // argparse commands must not be retried from every lifecycle event.
  const [continuationQueueEnabled, mediaQueueEnabled] = await Promise.all([
    sessionsCommandSupportedForTest("continuation"),
    responseMediaAutomationEnabledForTest()
      ? sessionsCommandSupportedForTest("media")
      : Promise.resolve(false),
  ]);
  const assistantTextParts = new Map();
  const presenceSourceID = randomUUID();
  const presenceGeneration = Date.now();
  let presenceSequence = 0;
  let presenceFailureReported = false;
  const presenceScheduler = createPresenceSchedulerForTest({
    persist: async (record) => {
      try {
        await persistPresence(record);
        presenceFailureReported = false;
      } catch (error) {
        if (!presenceFailureReported) {
          console.warn(`[OpenMates presence diagnostic] ${error?.message || error}`);
          presenceFailureReported = true;
        }
      }
    },
  });

  const schedulePresence = (state) => {
    const record = {
      ...state,
      hook_runtime_hash: HOOK_RUNTIME_HASH,
      source_id: presenceSourceID,
      generation: presenceGeneration,
      sequence: ++presenceSequence,
      updated_at: state.updated_at || isoNow(),
    };
    presenceStates.set(state.session_id, record);
    const notifierSessionID = record.top_level_session_id || record.parent_id || record.session_id;
    if (notifierSessionID && presenceIsLive(record)) notifierLiveSessions.add(notifierSessionID);
    presenceScheduler.schedule(record);
  };
  const currentPresence = (sessionID) => {
    const persisted = presenceData();
    const marker = persisted.child_roles?.[sessionID];
    if (presenceStates.has(sessionID)) {
      const current = presenceStates.get(sessionID);
      return marker?.parent_id ? { ...current, parent_id: marker.parent_id, top_level_session_id: marker.parent_id, child_role: marker.role } : current;
    }
    const initial = initialPresenceForTest(sessionID, {
      questionCapability: "unsupported",
      childRole: marker?.role || "unknown",
    });
    const persistedRecord = persisted.sessions?.[sessionID];
    if (persistedRecord && typeof persistedRecord === "object") Object.assign(initial, persistedRecord);
    if (marker?.parent_id) {
      initial.parent_id = marker.parent_id;
      initial.top_level_session_id = marker.parent_id;
    }
    return initial;
  };
  const recordLifecycleEvent = (event) => {
    const sessionID = eventSessionID(event);
    if (!sessionID) return;
    let current = currentPresence(sessionID);
    if (event.type.startsWith("question.")) {
      current = { ...current, capabilities: { ...current.capabilities, question: "supported" } };
    }
    schedulePresence(reducePresenceEventForTest(current, event));
  };
  const markToolState = (sessionID, paths = [], finished = false) => {
    if (!sessionID) return;
    const now = isoNow();
    const current = currentPresence(sessionID);
    schedulePresence({
      ...current,
      execution: finished && current.turn === "completed" ? "idle" : "busy",
      paths: finished ? [] : paths,
      heartbeat_at: now,
      updated_at: now,
    });
  };
  const recordResolvedChildRole = async (route) => {
    if (
      !route?.inheritedParentRoute
      || !route.requestingOpenCodeSessionID
      || !route.topLevelOpenCodeSessionID
      || !["read_only", "reviewer", "writable"].includes(route.childRole)
      || recordedChildRoles.has(route.requestingOpenCodeSessionID)
    ) return;
    const result = await runProcess(
      "python3",
      [
        "scripts/sessions.py", "presence", "child-role",
        "--session", route.requestingOpenCodeSessionID,
        "--parent", route.topLevelOpenCodeSessionID,
        "--role", route.childRole,
        "--if-unset",
      ],
      { cwd: CURRENT_CONTROL_PLANE_ROOT },
    );
    if (result.status !== 0) {
      throw new Error(`Could not persist authoritative child role: ${result.stderr || result.stdout}`);
    }
    recordedChildRoles.add(route.requestingOpenCodeSessionID);
  };
  const continuationCommand = async (action, sessionID, signal = null) => {
    if (!continuationQueueEnabled) return null;
    const args = ["scripts/sessions.py", "continuation", action, "--session", sessionID];
    if (action === "record" && signal) {
      args.push(
        "--operation-type", signal.operation_type,
        "--operation-key", signal.operation_key,
        "--next-action", signal.next_action,
      );
    }
    const result = await runProcess("python3", args, { cwd: CURRENT_CONTROL_PLANE_ROOT });
    if (result.status !== 0) throw new Error(result.stderr || result.stdout || `continuation ${action} failed`);
    return JSON.parse(result.stdout || "{}").continuation || null;
  };
  const taskContextForSession = async (sessionID, { refresh = false } = {}) => {
    if (!sessionID) return null;
    if (!refresh && taskContextCache.has(sessionID)) return taskContextCache.get(sessionID);
    try {
      const snapshot = await taskBridge("context", sessionID);
      taskContextCache.set(sessionID, snapshot);
      return snapshot;
    } catch (error) {
      console.warn(`[OpenMates Task bridge diagnostic] context failed: ${error?.message || error}`);
      const failed = { decision: "failed_closed", active: null, remaining: [] };
      taskContextCache.set(sessionID, failed);
      return failed;
    }
  };
  const reconcileTasksAtIdle = async (sessionID) => {
    const current = currentPresence(sessionID);
    if (taskBridgeSuppressedForTest(current)) return null;
    try {
      const result = await taskBridge("reconcile", sessionID);
      taskContextCache.delete(sessionID);
      if (result?.continuation) readyContinuationSessions.add(sessionID);
      return result;
    } catch (error) {
      console.warn(`[OpenMates Task bridge diagnostic] reconciliation failed closed: ${error?.message || error}`);
      return null;
    }
  };
  const openMatesTaskTool = openCodeTool ? openCodeTool({
    description: "Read or mutate encrypted OpenMates Tasks associated with this top-level OpenCode chat.",
    args: {
      action: openCodeTool.schema.enum(["context", "show", "create", "start", "edit", "block", "unblock", "done"]),
      task_id: openCodeTool.schema.string().optional(),
      title: openCodeTool.schema.string().optional(),
      description: openCodeTool.schema.string().optional(),
      status: openCodeTool.schema.enum(["backlog", "todo", "in_progress", "blocked", "done"]).optional(),
      reason_code: openCodeTool.schema.enum([
        "needs_user_input", "waiting_for_approval", "missing_credentials", "ambiguous_requirement",
        "external_dependency", "environment_unavailable", "verification_failed", "other",
      ]).optional(),
      reason_text: openCodeTool.schema.string().optional(),
    },
    async execute(args, context) {
      const route = await resolveWorktreeRoute(client, context.sessionID, routingData || sessionsData());
      const topLevelSessionID = route.topLevelOpenCodeSessionID || context.sessionID;
      const result = await taskBridge("tool", topLevelSessionID, { payload: args });
      taskContextCache.delete(topLevelSessionID);
      taskContextCache.delete(context.sessionID);
      return JSON.stringify(result);
    },
  }) : null;
  const ensureImplicitTaskBeforeMutation = async ({ sessionID, tool, command = "" }) => {
    if (!EDIT_TOOLS.has(tool)) return null;
    const snapshot = await taskContextForSession(sessionID, { refresh: true });
    const session = await openCodeSession(client, sessionID);
    const payload = implicitTaskMutationPayloadForTest(snapshot, {
      tool,
      command,
      sessionTitle: session?.title || "",
    });
    if (!payload) return null;
    const created = await taskBridge("tool", sessionID, { payload });
    taskContextCache.delete(sessionID);
    return created;
  };
  const mediaCommand = async (action, sessionID, artifact = null) => {
    if (!mediaQueueEnabled) return null;
    const args = ["scripts/sessions.py", "media", action, "--session", sessionID];
    if (action === "record" && artifact) {
      args.push(
        "--artifact-type", artifact.artifact_type,
        "--artifact-key", artifact.artifact_key,
        "--snippet", artifact.snippet,
      );
      if (artifact.artifact_path) args.push("--artifact-path", artifact.artifact_path);
    } else if (["ack", "release"].includes(action) && artifact?.artifact_key) {
      args.push("--artifact-key", artifact.artifact_key);
    } else if (action === "fail" && artifact?.artifact_key) {
      args.push("--artifact-key", artifact.artifact_key);
      if (artifact.failure_reason) args.push("--reason", artifact.failure_reason);
    }
    const result = await runProcess("python3", args, { cwd: CURRENT_CONTROL_PLANE_ROOT });
    if (result.status !== 0) throw new Error(result.stderr || result.stdout || `media ${action} failed`);
    return JSON.parse(result.stdout || "{}").media || null;
  };
  const failMediaRecord = async (sessionID, record, reason) => {
    await mediaCommand("fail", sessionID, { ...record, failure_reason: reason });
    console.warn(`[OpenMates response-media diagnostic] ${reason}`);
  };
  const uploadPendingFigmaExport = async (sessionID, record) => {
    if (record?.artifact_type !== "figma_export") return record;
    const route = await resolveWorktreeRoute(client, sessionID, routingData || sessionsData());
    const rawPath = figmaExportPathFromRecordForTest(record);
    const resolvedPath = resolveExistingFigmaExportPathForTest(rawPath, {
      cwd: route.worktreePath || instanceDirectory,
      worktreePath: route.worktreePath || "",
    });
    if (!resolvedPath) {
      await failMediaRecord(
        sessionID,
        record,
        `Figma export delivery skipped because the PNG is missing: ${rawPath || record.artifact_key}`,
      );
      return null;
    }
    const upload = await runProcess(
      "python3",
      [
        "scripts/opencode_response_media.py",
        resolvedPath,
        "--alt",
        "Figma reference: current screen/frame",
        "--output",
        "markdown",
      ],
      { cwd: CURRENT_CONTROL_PLANE_ROOT, timeoutMs: 120_000 },
    );
    if (upload.status !== 0) {
      await failMediaRecord(
        sessionID,
        record,
        `Figma export upload failed for ${resolvedPath}: ${(upload.stderr || upload.stdout || "").trim()}`,
      );
      return null;
    }
    const markdown = firstResponseMediaImageSnippetForTest(upload.stdout);
    if (!markdown) {
      await failMediaRecord(
        sessionID,
        record,
        `Figma export upload returned no image Markdown for ${resolvedPath}`,
      );
      return null;
    }
    return await mediaCommand("record", sessionID, {
      artifact_type: "figma_image",
      artifact_key: record.artifact_key,
      artifact_path: resolvedPath,
      snippet: markdown,
    });
  };
  const deliverPendingMedia = async (sessionID) => {
    if (!mediaQueueEnabled) return false;
    const current = currentPresence(sessionID);
    if (continuationSuppressedForTest(current) || automaticDeliverySessions.has(sessionID)) return false;
    automaticDeliverySessions.add(sessionID);
    let record = null;
    try {
      record = await mediaCommand("claim", sessionID);
      if (!record) return false;
      record = await uploadPendingFigmaExport(sessionID, record);
      if (!record) return false;
      const prompt = mediaDeliveryPromptForTest(record);
      if (!prompt) {
        await mediaCommand("fail", sessionID, { ...record, failure_reason: "media record had no deliverable prompt" });
        return false;
      }
      claimedMediaBySession.set(sessionID, record);
      const response = await client.session.promptAsync({
        path: { id: sessionID },
        body: {
          messageID: record.message_id,
          parts: [{ type: "text", text: prompt }],
        },
      });
      if (response?.error) throw new Error(String(response.error?.message || response.error));
      return true;
    } catch (error) {
      claimedMediaBySession.delete(sessionID);
      if (record) await mediaCommand("release", sessionID, record);
      console.warn(`[OpenMates response-media diagnostic] ${error?.message || error}`);
      return false;
    } finally {
      automaticDeliverySessions.delete(sessionID);
    }
  };
  const deliverReadyContinuation = async (sessionID) => {
    if (!continuationQueueEnabled) return false;
    const current = currentPresence(sessionID);
    if (continuationSuppressedForTest(current) || automaticDeliverySessions.has(sessionID)) return false;
    automaticDeliverySessions.add(sessionID);
    let record = null;
    try {
      record = await continuationCommand("claim", sessionID);
      if (!record) return false;
      readyContinuationSessions.delete(sessionID);
      const response = await client.session.promptAsync({
        path: { id: sessionID },
        body: {
          messageID: record.message_id,
          parts: [{ type: "text", text: taskContinuationPromptForTest(record) }],
        },
      });
      if (response?.error) throw new Error(String(response.error?.message || response.error));
      await continuationCommand("ack", sessionID);
      return true;
    } catch (error) {
      if (record) await continuationCommand("release", sessionID);
      console.warn(`[OpenMates continuation diagnostic] ${error?.message || error}`);
      return false;
    } finally {
      automaticDeliverySessions.delete(sessionID);
    }
  };
  const reconcileAuthoritativePresence = async () => {
    if (typeof client?.session?.status !== "function") return;
    const response = await client.session.status();
    const statuses = response?.data || response || {};
    const authoritativePending = {};
    const pendingQueries = [];
    if (typeof client?.permission?.list === "function") {
      pendingQueries.push(client.permission.list().then((response) => {
        const items = response?.data || response || [];
        if (Array.isArray(items)) authoritativePending.permissionIDs = new Set(items.map((item) => item?.id).filter(Boolean));
      }));
    }
    if (typeof client?.question?.list === "function") {
      pendingQueries.push(client.question.list().then((response) => {
        const items = response?.data || response || [];
        if (Array.isArray(items)) authoritativePending.questionIDs = new Set(items.map((item) => item?.id).filter(Boolean));
      }));
    }
    if (pendingQueries.length) await Promise.allSettled(pendingQueries);
    const reconciledPending = Object.keys(authoritativePending).length ? authoritativePending : null;
    const persistedSessions = presenceData().sessions || {};
    for (const [sessionID, record] of Object.entries(persistedSessions)) {
      if (!presenceStates.has(sessionID)) presenceStates.set(sessionID, record);
    }
    for (const record of reconcilePresenceStatesForTest(
      [...presenceStates.values()],
      statuses,
      { authoritativePending: reconciledPending },
    )) {
      schedulePresence(record);
    }
  };
  const reconciliationTimer = setInterval(() => {
    reconcileAuthoritativePresence().catch((error) => {
      console.warn(`[OpenMates presence reconciliation diagnostic] ${error?.message || error}`);
    });
  }, PRESENCE_HEARTBEAT_MS);
  reconciliationTimer.unref?.();
  reconcileAuthoritativePresence().catch(() => {});

  return {
    ...(openMatesTaskTool ? { tool: { openmates_task: openMatesTaskTool } } : {}),
    "experimental.chat.system.transform": async (input, output) => {
      if (!input?.sessionID) return;
      const snapshot = await taskContextForSession(input.sessionID);
      const context = taskContextSystemTextForTest(snapshot);
      if (context) output.system.push(context);
    },
    "experimental.session.compacting": async (input, output) => {
      if (!input?.sessionID) return;
      const snapshot = await taskContextForSession(input.sessionID, { refresh: true });
      const context = taskContextSystemTextForTest(snapshot);
      if (context) output.context.push(context);
    },
    event: async ({ event }) => {
      // Streaming part updates are extremely frequent and session.status already
      // carries the busy/idle lifecycle needed by presence tracking.
      if (event.type !== "message.part.updated") recordLifecycleEvent(event);
      const textPart = assistantTextPartForTest(event);
      if (textPart) {
        const parts = assistantTextParts.get(textPart.messageID) || new Map();
        parts.set(textPart.partID, textPart.text);
        assistantTextParts.set(textPart.messageID, parts);
      }
      if (event.type === "message.updated" && event.properties?.info?.role === "user") {
        const userSessionID = eventSessionID(event);
        taskContextCache.delete(userSessionID);
        scheduleWorktreeActivation(userSessionID);
        try {
          await continuationCommand("cancel", userSessionID);
          readyContinuationSessions.delete(userSessionID);
        } catch (error) {
          console.warn(`[OpenMates continuation diagnostic] ${error?.message || error}`);
        }
      }
      if (event.type === "session.idle") {
        const idleSessionID = eventSessionID(event);
        scheduleWorktreeCheckpoint(idleSessionID, "idle");
        await reconcileTasksAtIdle(idleSessionID);
        if (!(await deliverPendingMedia(idleSessionID))) await deliverReadyContinuation(idleSessionID);
      }
      if (event.type === "session.deleted") scheduleWorktreeCheckpoint(eventSessionID(event), "closed");
      const completedMessageID = completedAssistantMessageID(event);
      if (completedMessageID) {
        const completedSessionID = eventSessionID(event);
        const completedRoute = await resolveWorktreeRoute(client, completedSessionID, routingData || sessionsData());
        const taskCompletion = taskBridgeCompletionForTest(event, {
          topLevelSessionID: completedRoute.topLevelOpenCodeSessionID || completedSessionID,
        });
        if (taskCompletion) {
          try {
            await taskBridge("stage", taskCompletion.sessionID, { messageID: taskCompletion.messageID });
            taskContextCache.delete(taskCompletion.sessionID);
          } catch (error) {
            console.warn(`[OpenMates Task bridge diagnostic] stage failed closed: ${error?.message || error}`);
          }
        }
        const completedText = [...(assistantTextParts.get(completedMessageID)?.values() || [])].join("\n");
        assistantTextParts.delete(completedMessageID);
        const requiredMedia = claimedMediaBySession.get(completedSessionID) || pendingMediaBySession.get(completedSessionID);
        if (requiredMedia && responseContainsMediaForTest(completedText, requiredMedia)) {
          try {
            await mediaCommand("ack", completedSessionID, requiredMedia);
            claimedMediaBySession.delete(completedSessionID);
            pendingMediaBySession.delete(completedSessionID);
          } catch (error) {
            console.warn(`[OpenMates response-media diagnostic] ${error?.message || error}`);
          }
        } else if (claimedMediaBySession.has(completedSessionID)) {
          try {
            await mediaCommand("release", completedSessionID, requiredMedia);
            claimedMediaBySession.delete(completedSessionID);
          } catch (error) {
            console.warn(`[OpenMates response-media diagnostic] ${error?.message || error}`);
          }
        }
        const current = currentPresence(completedSessionID);
        const notifierSessionID = current.top_level_session_id || current.parent_id || completedSessionID;
        if (notifierLiveSessions.has(notifierSessionID)) {
          notifierLiveSessions.delete(notifierSessionID);
          scheduleNotifierEvent(notifierEventArgsForTest({ eventType: "response-completed", sessionID: completedSessionID, messageID: completedMessageID }));
        }
      }
    },
    "shell.env": async (input, output) => {
      if (!input?.sessionID) return;
      const route = await resolveWorktreeRoute(client, input.sessionID, routingData || sessionsData());
      output.env ||= {};
      output.env.OPENCODE_SESSION_ID = route.topLevelOpenCodeSessionID || input.sessionID;
      if (route.worktreePath) output.env.OPENMATES_SESSION_WORKTREE = route.worktreePath;
      output.env.OPENMATES_PROFILE = "opencode-personal";
      output.env.OPENMATES_ACCOUNT_GUARD = "required";
      output.env.OPENMATES_API_URL = "https://api.dev.openmates.org";
      output.env.OPENMATES_STATE_DIR = "";
      for (const key of SECRET_ENV_KEYS) output.env[key] = "";
    },
    "tool.execute.before": async (input, output) => withHookDeadlineForTest(
      "tool.execute.before",
      input?.sessionID,
      async () => {
      const tool = input.tool || "";
      const githubMcpGuard = githubMcpGuardDecisionForTest(tool);
      if (githubMcpGuard.decision === "block") throw new Error(githubMcpGuard.message);
      if (!BASH_TOOLS.has(tool) && !EDIT_TOOLS.has(tool) && !READ_TOOLS.has(tool) && !SEARCH_TOOLS.has(tool) && !TASK_TOOLS.has(tool)) return;

      const controlPlaneDecision = controlPlaneToolDecisionForTest({
        tool,
        args: output?.args || input?.args || {},
        cwd: instanceDirectory,
      });
      if (controlPlaneDecision.decision === "block") throw new Error(controlPlaneDecision.message);

      if (BASH_TOOLS.has(tool)) {
        const command = bashCommand(output?.args || input?.args);
        const cliIsolation = openMatesCliIsolationDecisionForTest(command);
        if (cliIsolation.decision === "block") throw new Error(cliIsolation.message);
        guardBash(command, input.sessionID);
        const longSleep = opaqueLongSleepDecisionForTest(command);
        if (longSleep.decision === "block") throw new Error(longSleep.message);
      }
      if (
        (BASH_TOOLS.has(tool) || EDIT_TOOLS.has(tool) || TASK_TOOLS.has(tool))
        && readyContinuationSessions.has(input.sessionID)
        && !/scripts\/sessions\.py\s+continuation\b/.test(bashCommand(output?.args || input?.args))
      ) {
        try {
          await continuationCommand("cancel", input.sessionID);
          readyContinuationSessions.delete(input.sessionID);
        } catch (error) {
          console.warn(`[OpenMates continuation diagnostic] ${error?.message || error}`);
        }
      }
      bindSessionStart(input, output);

      const route = await resolveWorktreeRoute(client, input.sessionID, routingData || sessionsData());
      const routedOpenCodeSessionID = route.topLevelOpenCodeSessionID || input.sessionID;
      await recordResolvedChildRole(route);
      if (BASH_TOOLS.has(tool)) await guardWorkerBashGate(bashCommand(output?.args || input?.args), routedOpenCodeSessionID);
      const childMutation = childMutationDecisionForTest(route, tool, bashCommand(output?.args || input?.args));
      if (childMutation.decision === "block") {
        const key = `child:${input.sessionID}:${tool}:${bashCommand(output?.args || input?.args)}`;
        const count = (routingBlockCounts.get(key) || 0) + 1;
        routingBlockCounts.set(key, count);
        throw new Error(repeatedRoutingFailureMessageForTest(childMutation.message, count));
      }
      const routeRecorded = recordRouting
        && route.decision === "worktree_routed"
        && route.topLevelOpenCodeSessionID
        && !recordedRoutes.has(route.topLevelOpenCodeSessionID)
        && await recordWorktreeRouting(route.topLevelOpenCodeSessionID);
      if (
        recordRouting
        && routeRecorded
      ) {
        recordedRoutes.add(route.topLevelOpenCodeSessionID);
      }
      await ensureImplicitTaskBeforeMutation({
        sessionID: routedOpenCodeSessionID,
        tool,
        command: BASH_TOOLS.has(tool) ? bashCommand(output?.args || input?.args) : "",
      });
      if (route.decision !== "worktree_routed") {
        const currentArgs = output?.args || input?.args;
        const command = bashCommand(currentArgs);
        if (BASH_TOOLS.has(tool) && improvementReviewCommandIsSafe(command)) {
          replaceToolArgs(output, currentArgs, { ...currentArgs, workdir: PROJECT_ROOT });
        }
        const failure = routingFailureForTest({
          tool,
          sessionID: input.sessionID,
          command,
          routeMessage: route.message || "",
          routeDecision: route.decision,
          mergedCommit: route.session?.worktree?.merged_commit || "",
        });
        if (failure.decision === "block") {
          const key = `route:${input.sessionID}:${tool}:${command}`;
          const count = (routingBlockCounts.get(key) || 0) + 1;
          routingBlockCounts.set(key, count);
          throw new Error(repeatedRoutingFailureMessageForTest(failure.message, count));
        }
      }

      if (BASH_TOOLS.has(tool) && !route.worktreePath) {
        const currentArgs = output?.args || input?.args;
        const command = bashCommand(currentArgs);
        if (
          improvementReviewCommandIsSafe(command)
          || isApprovedControlPlaneAuditCommand(command)
          || exactCommitDeployedTestForTest(command, route.session?.worktree?.merged_commit || "")
        ) {
          replaceToolArgs(output, currentArgs, { ...toolInput(currentArgs), command, workdir: PROJECT_ROOT });
        }
      }

      if (BASH_TOOLS.has(tool) && !route.worktreePath) {
        const currentArgs = output?.args || input?.args;
        const command = bashCommand(currentArgs);
        if (isApprovedControlPlaneAuditCommand(command) || exactCommitDeployedTestForTest(command, route.session?.worktree?.merged_commit || "")) {
          replaceToolArgs(output, currentArgs, { ...toolInput(currentArgs), command, workdir: PROJECT_ROOT });
        }
      }

      if (TASK_TOOLS.has(tool)) {
        const agent = String(toolInput(output?.args || input?.args).subagent_type || "");
        const generation = sourceGenerations.get(routedOpenCodeSessionID) || 0;
        const reviewDecision = reviewerSpawnDecisionForTest({
          agent,
          generation,
          lastReviewedGeneration: reviewedGenerations.get(routedOpenCodeSessionID),
        });
        if (reviewDecision.decision === "block") throw new Error(reviewDecision.message);
        return;
      }

      if (route.worktreePath) {
        const currentArgs = output?.args || input?.args;
        const routedArgs = routeLocalToolArgsWithCircuitBreakerForTest(
          tool,
          currentArgs,
          route.worktreePath,
          { sessionID: input.sessionID, counts: routingBlockCounts },
        );
        replaceToolArgs(output, currentArgs, routedArgs);
      }
      if (EDIT_TOOLS.has(tool)) {
        const files = editedFilesForTest(output?.args || input?.args, route.worktreePath || instanceDirectory);
        const relativePaths = files.map((file) => routedEditRelativePathForTest(file, route.worktreePath || "")).filter(Boolean);
        await guardWorkerEditPaths(files, relativePaths, routedOpenCodeSessionID);
        markToolState(routedOpenCodeSessionID, relativePaths);
        await guardWorkerEditGate(relativePaths, routedOpenCodeSessionID);
        await runStaleRead("check", files, routedOpenCodeSessionID);
        guardRootEdit(files, routedOpenCodeSessionID, route.worktreePath);
        const routedDirectory = route.worktreePath || instanceDirectory;
        await runBridge("PreToolUse", bridgePayload("PreToolUse", tool, output?.args, routedDirectory), routedOpenCodeSessionID, routedDirectory);
        await editLease("acquire", files, routedOpenCodeSessionID);
        return;
      }
      const routedDirectory = route.worktreePath || instanceDirectory;
        await runBridge("PreToolUse", bridgePayload("PreToolUse", tool, output?.args, routedDirectory), routedOpenCodeSessionID, routedDirectory);
      },
    ),
    "tool.execute.after": async (input, output) => {
      const tool = input.tool || "";
      if (TASK_TOOLS.has(tool)) {
        await recordTaskChildRole(input, output);
        const agent = String(toolInput(toolArgs(input, output)).subagent_type || "");
        if (REVIEWER_SUBAGENTS.has(agent)) {
          const route = await resolveWorktreeRoute(client, input.sessionID, routingData || sessionsData());
          const topLevelSessionID = route.topLevelOpenCodeSessionID || input.sessionID;
          reviewedGenerations.set(topLevelSessionID, sourceGenerations.get(topLevelSessionID) || 0);
        }
        return;
      }
      if (BASH_TOOLS.has(tool)) {
        const command = bashCommand(toolArgs(input, output));
        const mediaRoute = await resolveWorktreeRoute(client, input.sessionID, routingData || sessionsData());
        const mediaCwd = output?.args?.workdir || mediaRoute.worktreePath || instanceDirectory;
        if (isCliAuthFailure(command, output?.output || "")) {
          output.output += "\n\n[OpenMates personal CLI login required]\nRun `openmates login` and approve the intended personal dev account.";
        }
        appendCommandDoctorHint(command, output);
        appendFailedTestLeaseHint(command, output);
        appendTemporaryLockWaitHint(output);
        appendApiHealthWaitHint(output);
        appendResponseMediaEmbedHint(command, output);
        appendFigmaReferenceEmbedHint({ tool, command, cwd: mediaCwd, worktreePath: mediaRoute.worktreePath || "" }, output);
        const mediaArtifact = responseMediaArtifactForTest({
          command,
          output: output?.output || "",
          cwd: mediaCwd,
          worktreePath: mediaRoute.worktreePath || "",
          requireExistingFigmaExport: true,
        });
        if (mediaArtifact) {
          try {
            const record = await mediaCommand("record", input.sessionID, mediaArtifact);
            if (record) pendingMediaBySession.set(input.sessionID, record);
          } catch (error) {
            console.warn(`[OpenMates response-media diagnostic] ${error?.message || error}`);
          }
        }
        const continuationSignal = continuationSignalForTest(output?.output || "");
        if (continuationSignal) {
          try {
            await continuationCommand("record", input.sessionID, continuationSignal);
            readyContinuationSessions.add(input.sessionID);
          } catch (error) {
            console.warn(`[OpenMates continuation diagnostic] ${error?.message || error}`);
          }
        }
        if (/python3\s+scripts\/sessions\.py\s+start\b/.test(command)) {
          await recordWorktreeRouting(input.sessionID);
        }
      } else {
        const mediaRoute = await resolveWorktreeRoute(client, input.sessionID, routingData || sessionsData());
        const mediaCwd = mediaRoute.worktreePath || instanceDirectory;
        appendFigmaReferenceEmbedHint({ tool, cwd: mediaCwd, worktreePath: mediaRoute.worktreePath || "" }, output);
        const mediaArtifact = responseMediaArtifactForTest({
          output: output?.output || "",
          cwd: mediaCwd,
          worktreePath: mediaRoute.worktreePath || "",
          requireExistingFigmaExport: true,
        });
        if (mediaArtifact) {
          try {
            const record = await mediaCommand("record", input.sessionID, mediaArtifact);
            if (record) pendingMediaBySession.set(input.sessionID, record);
          } catch (error) {
            console.warn(`[OpenMates response-media diagnostic] ${error?.message || error}`);
          }
        }
      }
      if (READ_TOOLS.has(tool) || SEARCH_TOOLS.has(tool)) {
        const route = await resolveWorktreeRoute(client, input.sessionID, routingData || sessionsData());
        const routedOpenCodeSessionID = route.topLevelOpenCodeSessionID || input.sessionID;
        const files = explicitFilesForTest(toolArgs(input, output), route.worktreePath || instanceDirectory);
        await runStaleRead("record", files, routedOpenCodeSessionID);
        if (READ_TOOLS.has(tool) && output && typeof output.output === "string") {
          for (const file of files) {
            const warning = readConflictWarningForTest({
              path: file,
              sessionID: routedOpenCodeSessionID,
              data: routingData || sessionsData(),
              presence: presenceData(),
            });
            if (warning && !output.output.includes(warning)) output.output += `\n\n${warning}`;
          }
        }
      }
      if (!EDIT_TOOLS.has(tool)) return;
      const route = await resolveWorktreeRoute(client, input.sessionID, routingData || sessionsData());
      const routedDirectory = route.worktreePath || instanceDirectory;
      const routedOpenCodeSessionID = route.topLevelOpenCodeSessionID || input.sessionID;
      const files = editedFilesForTest(toolArgs(input, output), routedDirectory);
      try {
        await runBridge("PostToolUse", bridgePayload("PostToolUse", tool, toolArgs(input, output), routedDirectory), routedOpenCodeSessionID, routedDirectory);
        await runStaleRead("sync", files, routedOpenCodeSessionID);
      } finally {
        sourceGenerations.set(
          routedOpenCodeSessionID,
          (sourceGenerations.get(routedOpenCodeSessionID) || 0) + 1,
        );
        await editLease("release", files, routedOpenCodeSessionID);
        markToolState(routedOpenCodeSessionID, [], true);
      }
    },
  };
};

OpenMatesHooks.test = Object.freeze({
  bindSessionStart,
  childRoleFromAgent,
  childMutationDecisionForTest,
  reviewerSpawnDecisionForTest,
  continuationSignalForTest,
  continuationSuppressedForTest,
  taskBridgeCompletionForTest,
  taskBridgeSuppressedForTest,
  taskContextSystemTextForTest,
  implicitTaskMutationPayloadForTest,
  taskContinuationPromptForTest,
  controlPlaneToolDecisionForTest,
  directSessionsSpawnChatCommandForTest,
  createWorktreeActivationSchedulerForTest,
  createWorktreeCheckpointSchedulerForTest,
  createPresenceSchedulerForTest,
  dockerMutationDecisionForTest,
  editedFilesForBindingForTest,
  editedFilesForTest,
  hookRuntimeDiagnosticForTest,
  githubMcpGuardDecisionForTest,
  initialPresenceForTest,
  exactCommitDeployedTestForTest,
  isApprovedControlPlaneAuditCommand,
  isReadOnlyChildBash,
  isTodoWriteTool,
  opaqueLongSleepDecisionForTest,
  openMatesCliIsolationDecisionForTest,
  presenceIsLive,
  readConflictWarningForTest,
  repeatedRoutingFailureMessageForTest,
  completedAssistantMessageID,
  apiHealthWaitUrlForTest,
  approvedProofVideoSourceTokenForTest,
  appendFigmaReferenceEmbedHint,
  appendResponseMediaEmbedHint,
  figmaExportPathForTest,
  figmaExportPathFromRecordForTest,
  firstResponseMediaImageSnippetForTest,
  firstResponseMediaVideoSnippetForTest,
  canonicalResponseMediaKeySourceForTest,
  resolveExistingFigmaExportPathForTest,
  responseMediaArtifactForTest,
  responseMediaAutomationEnabledForTest,
  responseMediaVideoProducerCommandForTest,
  sessionsCommandSupportedForTest,
  validResponseMediaVideoSnippetForTest,
  mediaDeliveryPromptForTest,
  responseContainsMediaForTest,
  assistantTextPartForTest,
  sleepDurationSecondsForTest,
  notifierEventArgsForTest,
  temporaryLockWaitTypesForTest,
  reducePresenceEventForTest,
  reconcilePresenceStatesForTest,
  runProcessForTest: runProcess,
  resolveWorktreeRouteForTest,
  routeLocalToolArgsWithCircuitBreakerForTest,
  rewriteEditArgsForTest,
  rootGuardDecisionForTest,
  routedEditRelativePathForTest,
  routeLocalToolArgsForTest,
  routingDecisionForTest,
  routingFailureForTest,
  taskChildClassificationForTest,
  workerBashGateDecisionForTest,
  workerEditGateDecisionForTest,
  workerEditPathDecisionForTest,
  warnOnceForTest,
  warningReasonForTest,
  withHookDeadlineForTest,
});
