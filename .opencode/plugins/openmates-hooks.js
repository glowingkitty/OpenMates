// OpenMates OpenCode hook bridge.
//
// Keep interactive edits fast. Durable checks belong at test and deploy time;
// hooks only prevent unambiguous unsafe operations and preserve compatibility
// with the small set of canonical Claude guards.

import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

const EDIT_TOOLS = new Set(["apply_patch", "edit", "write", "Edit", "Write"]);
const READ_TOOLS = new Set(["read", "Read"]);
const SEARCH_TOOLS = new Set(["glob", "grep", "Glob", "Grep"]);
const BASH_TOOLS = new Set(["bash", "Bash"]);
const TASK_TOOLS = new Set(["task", "Task"]);
const PROJECT_ROOT = process.env.OPENMATES_PROJECT_ROOT || "/home/superdev/projects/OpenMates";
const WORKTREE_ROOTS = [
  `${PROJECT_ROOT}/.openmates-agent-worktrees`,
  `${PROJECT_ROOT}/.agent-worktrees`,
  "/home/superdev/projects/.openmates-agent-worktrees",
];
const BRIDGE = `${PROJECT_ROOT}/.codex/hooks/claude-hook-bridge.sh`;
const SESSIONS_FILE = `${PROJECT_ROOT}/.claude/sessions.json`;
const PRESENCE_FILE = `${PROJECT_ROOT}/.opencode/presence.json`;
const PRESENCE_DEBOUNCE_MS = 250;
const PRESENCE_HEARTBEAT_MS = 30_000;
const PRESENCE_LIVE_EXECUTION = new Set(["busy", "retrying"]);
const REPO_RELATIVE_PREFIXES = ["frontend/", "backend/", "scripts/", "docs/", "apple/", ".opencode/", ".claude/"];
const SOURCE_FILE_EXTENSION = /\.(?:py|js|mjs|ts|tsx|svelte|swift|md|ya?ml|json)$/;
const CLI_LOGIN_HINT_MARKER = "[OpenMates CLI login hint]";
const COMMAND_DOCTOR_MARKER = "[OpenMates command doctor]";
const FAILED_TEST_LEASE_MARKER = "[OpenMates failed-test lease hint]";
const ROUTING_GUARD_MARKER = "[OpenMates worktree routing]";
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

function actionable(marker, reason, next) {
  return `${marker} Reason: ${reason} Next: ${next}`;
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

export function initialPresenceForTest(sessionID, { questionCapability = "unsupported", childRole = "unknown" } = {}) {
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

export function reducePresenceEventForTest(current, event, { now = isoNow() } = {}) {
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
    return parentID ? { ...state, parent_id: parentID, top_level_session_id: parentID } : state;
  }
  if (event.type === "openmates.child.role") {
    const role = properties.role;
    if (!["read_only", "reviewer", "writable"].includes(role)) return state;
    return { ...state, parent_id: properties.parentID, top_level_session_id: properties.parentID, child_role: role };
  }
  return state;
}

export function createPresenceSchedulerForTest({
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
      cwd: PROJECT_ROOT,
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

function presenceData() {
  try {
    const parsed = JSON.parse(readFileSync(PRESENCE_FILE, "utf8"));
    return parsed?.project_root === PROJECT_ROOT && parsed?.sessions ? parsed : { sessions: {}, task_claims: {}, child_roles: {} };
  } catch {
    return { sessions: {}, task_claims: {}, child_roles: {} };
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
  }
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

export function readConflictWarningForTest({ path = "", sessionID = "", data = {}, presence = {} } = {}) {
  const relativePath = collisionRelativePath(path, data);
  const lease = data?.edit_leases?.[relativePath];
  if (!lease) return "";
  const ownerRecord = data?.sessions?.[lease.session_id];
  const ownerOpenCodeID = ownerRecord?.opencode_session_id || "";
  if (!ownerOpenCodeID || samePresenceWorkUnit(sessionID, ownerOpenCodeID, presence)) return "";
  if (!presenceRecordIsLive(presence?.sessions?.[ownerOpenCodeID])) return "";
  return `[OpenMates presence conflict] ${relativePath} currently has a live edit by repository session ${lease.session_id}. This read remains allowed; re-read after the lease releases before editing.`;
}

export function routingDecisionForTest({ session = {} } = {}) {
  const worktreePath = ["active", "merged", "changes_pending"].includes(session?.worktree?.status) ? session.worktree.path || "" : "";
  if (worktreePath && isDirectManagedWorktree(worktreePath)) return { decision: "worktree_routed", worktreePath };
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

export async function resolveWorktreeRouteForTest({ sessionID, data = {}, childRoles = {}, getSession }) {
  let currentID = sessionID;
  let inheritedParentRoute = false;
  const visited = new Set();
  for (let depth = 0; currentID && depth < 12 && !visited.has(currentID); depth += 1) {
    visited.add(currentID);
    const record = activeSessionRecord(currentID, data);
    if (record) {
      const decision = routingDecisionForTest({ session: record.session });
      return {
        ...decision,
        repositorySessionID: record.id,
        topLevelOpenCodeSessionID: currentID,
        requestingOpenCodeSessionID: sessionID,
        inheritedParentRoute,
        childRole: childRoles?.[sessionID]?.role || "unknown",
        session: record.session,
      };
    }
    const info = await getSession(currentID);
    const parentID = info?.parentID || "";
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
    childRole: childRoles?.[sessionID]?.role || "unknown",
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
  if (!command || ["$(", "`", "<(", ">("].some((token) => command.includes(token)) || extractWriteTargets(command).length > 0) return false;
  const readOnlyCommands = new Set(["pgrep", "ps", "pwd"]);
  const readOnlyGitCommands = new Set(["diff", "log", "show", "status"]);
  const readOnlyDockerCommands = new Set(["inspect", "logs", "ps", "stats", "top"]);
  const readOnlyDebugSpecs = {
    chat: { booleanOptions: new Set(), valueOptions: new Set(), positional: 1 },
    issue: { booleanOptions: new Set(["--production", "--timeline"]), valueOptions: new Set(), positional: 1 },
    logs: { booleanOptions: new Set(["--o2"]), valueOptions: new Set(["--query-json"]), positional: 0 },
  };
  const readOnlyIssueSpecs = {
    show: { booleanOptions: new Set(), valueOptions: new Set(["--env"]), positional: 1 },
    timeline: { booleanOptions: new Set(["--compact"]), valueOptions: new Set(["--env"]), positional: 1 },
  };
  const argumentsMatch = (args, spec) => {
    if (!spec) return false;
    let positional = 0;
    for (let index = 0; index < args.length; index += 1) {
      const arg = args[index];
      if (!arg.startsWith("-")) {
        positional += 1;
        continue;
      }
      const option = arg.split("=", 1)[0];
      if (spec.booleanOptions.has(option)) continue;
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
  const debugCommandIsReadOnly = (action, args) => argumentsMatch(args, readOnlyDebugSpecs[action]);
  const issueCommandIsReadOnly = (args) => {
    if (args.length === 1 && ["-h", "--help"].includes(args[0])) return true;
    const action = args[0];
    return argumentsMatch(args.slice(1), readOnlyIssueSpecs[action]);
  };

  return commandSegmentTokens(command.replace(/\\\s*\n/g, " ")).every((tokens) => {
    const directScript = unquote(tokens[0] || "").replace(/^\.\//, "");
    if (directScript === "scripts/issues.py") return issueCommandIsReadOnly(tokens.slice(1));
    const invocation = normalizedInvocation(tokens);
    const commandName = invocation.command;
    const args = invocation.args;
    if (readOnlyCommands.has(commandName)) return true;
    if (commandName === "git") {
      const writesOutput = args.some((arg) => arg === "-o" || arg === "--output" || arg.startsWith("--output="));
      return !writesOutput && readOnlyGitCommands.has(firstNonOption(args));
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
      if (script === "scripts/sessions.py") return args.length === 2 && ["-h", "--help"].includes(args[1]);
      return false;
    }
    return false;
  });
}

export function childMutationDecisionForTest(route, tool, command = "") {
  if (!route?.inheritedParentRoute || (!EDIT_TOOLS.has(tool) && !BASH_TOOLS.has(tool))) {
    return { decision: "allow", message: "no inherited child mutation" };
  }
  if (BASH_TOOLS.has(tool) && isReadOnlyChildBash(command)) {
    return { decision: "allow", message: "read-only inherited child shell" };
  }
  const role = route.childRole || "unknown";
  const reason = role === "writable"
    ? "a writable child must own a separate repository session and disjoint worktree before mutating files"
    : `child role ${role} may read the parent worktree but may not mutate it`;
  return {
    decision: "block",
    message: actionable(
      "[OpenMates child ownership guard]",
      reason,
      "run the mutation in the parent session, or explicitly assign the child its own writable sessions.py worktree and disjoint file/task ownership.",
    ),
  };
}

function routingRecoveryMessage(sessionID) {
  return `${ROUTING_GUARD_MARKER} Reason: no active sessions.py worktree could be resolved for OpenCode session ${sessionID || "<unknown>"}. Next: run python3 scripts/sessions.py start --mode <feature|bug|docs|testing> --task \"brief description\". Safe reads, searches, status, summary, context, worktree ensure, and worktree repair remain available.`;
}

function isRecoveryBash(command) {
  return /python3\s+scripts\/sessions\.py\s+(?:start|status|summary|context|doctor)\b/.test(command)
    || /python3\s+scripts\/sessions\.py\s+worktree\s+(?:ensure|repair)\b/.test(command)
    || /^\s*(?:pwd|date|git\s+(?:status|log|diff|show)\b)/.test(command);
}

export function routingFailureForTest({ tool = "", sessionID = "", command = "" } = {}) {
  if (READ_TOOLS.has(tool) || SEARCH_TOOLS.has(tool)) return { decision: "allow_read", message: "" };
  if (BASH_TOOLS.has(tool) && isRecoveryBash(command)) return { decision: "allow_recovery", message: "" };
  return { decision: "block", message: routingRecoveryMessage(sessionID) };
}

export function routeLocalToolArgsForTest(tool, args, worktreePath) {
  const input = toolInput(args);
  if (!worktreePath) return input;
  if (BASH_TOOLS.has(tool)) {
    const command = bashCommand(input);
    if (command.includes("$'")) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: ANSI-C shell quoting can encode managed paths and bypass session isolation. Next: use ordinary quoted values and repository-relative paths inside ${worktreePath}.`);
    }
    const prodSshHelper = `${PROJECT_ROOT}/scripts/prod-ssh.sh`;
    const routedWorktree = resolve(worktreePath);
    const normalizedTokens = tokenizeCommand(command).map(shellUnescape);
    const tokensWithoutOwnWorktree = normalizedTokens.map((token) => token.split(routedWorktree).join(""));
    const rootReferences = tokensWithoutOwnWorktree
      .filter((token) => token.includes(PROJECT_ROOT));
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
    return { ...input, command, workdir: worktreePath };
  }
  if (SEARCH_TOOLS.has(tool)) {
    const routed = { ...input };
    if (typeof routed.path === "string" && targetsDifferentWorktree(routed.path, worktreePath)) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: the absolute search path targets another managed worktree. Next: use a repository-relative path inside ${worktreePath}.`);
    }
    if (typeof routed.path === "string" && !isAbsolute(routed.path)) {
      const target = resolve(worktreePath, routed.path);
      if (pathEscapesWorktree(target, worktreePath)) {
        throw new Error(`${ROUTING_GUARD_MARKER} Reason: the relative search path escapes the routed worktree. Next: use a path inside ${worktreePath}.`);
      }
    }
    routed.path = rewritePathForWorktree(routed.path || ".", worktreePath);
    return routed;
  }
  for (const key of ["file_path", "filePath", "path"]) {
    const value = input[key];
    if (typeof value !== "string") continue;
    if (targetsDifferentWorktree(value, worktreePath)) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: the absolute file path targets another managed worktree. Next: use a repository-relative path inside ${worktreePath}.`);
    }
    if (isAbsolute(value)) continue;
    const target = resolve(worktreePath, value);
    if (pathEscapesWorktree(target, worktreePath)) {
      throw new Error(`${ROUTING_GUARD_MARKER} Reason: the relative file path escapes the routed worktree. Next: use a repository-relative path inside ${worktreePath}.`);
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

function recordWorktreeRouting(opencodeSessionID) {
  if (!opencodeSessionID) return false;
  const result = spawnSync(
    "python3",
    ["scripts/sessions.py", "worktree", "repair", "--opencode-session", opencodeSessionID],
    { cwd: PROJECT_ROOT, encoding: "utf8" },
  );
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "routing repair failed").trim();
    console.warn(`${ROUTING_GUARD_MARKER} Reason: sessions.py could not record worktree routing. Next: run python3 scripts/sessions.py worktree repair --opencode-session ${opencodeSessionID}. Detail: ${detail}`);
    return false;
  }
  return true;
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
    message: actionable(
      DOCKER_LOCK_MARKER,
      "Docker Compose mutations require the current sessions.py Docker lock.",
      `run python3 scripts/sessions.py lock --session ${shortID} --type docker, retry once, then release immediately with python3 scripts/sessions.py unlock --session ${shortID} --type docker.`,
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
    `use a repository-relative path; if routing is missing, run python3 scripts/sessions.py worktree ensure --session ${sessionID || "<id>"}.`,
  );
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
    if (result.status === 2) {
      const detail = stderr || stdout || "the file changed since it was read";
      throw new Error(actionable("[OpenMates stale-read guard]", detail, `re-read ${file}, reapply the intended change to the latest content, then retry once.`));
    }
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
  if (result.status === 2) {
    const detail = stderr || stdout || "another live session holds an overlapping edit lease";
    throw new Error(actionable("[OpenMates edit lease guard]", detail, "re-read the file after the current lease releases, then retry once."));
  }
  if (result.status !== 0) {
    const detail = stderr || stdout || `edit lease command exited ${result.status}`;
    throw new Error(actionable("[OpenMates edit lease guard]", detail, "run python3 scripts/sessions.py status, resolve the reported session-state error, then retry."));
  }
}

export const OpenMatesHooks = async ({ client, directory, routingData, recordRouting = true } = {}) => {
  const instanceDirectory = directory || activeCwd();
  const recordedRoutes = new Set();
  const presenceStates = new Map();
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
      source_id: presenceSourceID,
      generation: presenceGeneration,
      sequence: ++presenceSequence,
      updated_at: state.updated_at || isoNow(),
    };
    presenceStates.set(state.session_id, record);
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
  const heartbeatTimer = setInterval(() => {
    const now = isoNow();
    for (const state of presenceStates.values()) {
      if (PRESENCE_LIVE_EXECUTION.has(state.execution)) schedulePresence({ ...state, heartbeat_at: now, updated_at: now });
    }
  }, PRESENCE_HEARTBEAT_MS);
  heartbeatTimer.unref?.();

  return {
    event: async ({ event }) => {
      recordLifecycleEvent(event);
    },
    "shell.env": async (input, output) => {
      if (!input?.sessionID) return;
      const route = await resolveWorktreeRoute(client, input.sessionID, routingData || sessionsData());
      output.env ||= {};
      output.env.OPENCODE_SESSION_ID = route.topLevelOpenCodeSessionID || input.sessionID;
      if (route.worktreePath) output.env.OPENMATES_SESSION_WORKTREE = route.worktreePath;
    },
    "tool.execute.before": async (input, output) => {
      const tool = input.tool || "";
      if (!BASH_TOOLS.has(tool) && !EDIT_TOOLS.has(tool) && !READ_TOOLS.has(tool) && !SEARCH_TOOLS.has(tool) && !TASK_TOOLS.has(tool)) return;

      if (BASH_TOOLS.has(tool)) guardBash(bashCommand(output?.args || input?.args), input.sessionID);
      bindSessionStart(input, output);

      const route = await resolveWorktreeRoute(client, input.sessionID, routingData || sessionsData());
      const routedOpenCodeSessionID = route.topLevelOpenCodeSessionID || input.sessionID;
      const childMutation = childMutationDecisionForTest(route, tool, bashCommand(output?.args || input?.args));
      if (childMutation.decision === "block") throw new Error(childMutation.message);
      if (
        recordRouting
        &&
        route.decision === "worktree_routed"
        && route.topLevelOpenCodeSessionID
        && !recordedRoutes.has(route.topLevelOpenCodeSessionID)
        && recordWorktreeRouting(route.topLevelOpenCodeSessionID)
      ) {
        recordedRoutes.add(route.topLevelOpenCodeSessionID);
      }
      if (route.decision !== "worktree_routed") {
        const failure = routingFailureForTest({
          tool,
          sessionID: input.sessionID,
          command: bashCommand(output?.args || input?.args),
        });
        if (failure.decision === "block") throw new Error(failure.message);
      }

      if (TASK_TOOLS.has(tool)) {
        return;
      }

      if (route.worktreePath) {
        const currentArgs = output?.args || input?.args;
        const routedArgs = routeLocalToolArgsForTest(tool, currentArgs, route.worktreePath);
        replaceToolArgs(output, currentArgs, routedArgs);
      }
      if (EDIT_TOOLS.has(tool)) {
        const files = editedFilesForTest(output?.args || input?.args, route.worktreePath || instanceDirectory);
        const relativePaths = files.map((file) => collisionRelativePath(file, routingData || sessionsData())).filter(Boolean);
        markToolState(routedOpenCodeSessionID, relativePaths);
        runStaleRead("check", files, routedOpenCodeSessionID);
        guardRootEdit(files, routedOpenCodeSessionID, route.worktreePath);
        const routedDirectory = route.worktreePath || instanceDirectory;
        runBridge("PreToolUse", bridgePayload("PreToolUse", tool, output?.args, routedDirectory), routedOpenCodeSessionID, routedDirectory);
        runEditLease("acquire", files, routedOpenCodeSessionID);
        return;
      }
      const routedDirectory = route.worktreePath || instanceDirectory;
      runBridge("PreToolUse", bridgePayload("PreToolUse", tool, output?.args, routedDirectory), routedOpenCodeSessionID, routedDirectory);
    },
    "tool.execute.after": async (input, output) => {
      const tool = input.tool || "";
      if (BASH_TOOLS.has(tool)) {
        const command = bashCommand(toolArgs(input, output));
        if (isCliAuthFailure(command, output?.output || "")) appendCliLoginHint(output);
        appendCommandDoctorHint(command, output);
        appendFailedTestLeaseHint(command, output);
        if (/python3\s+scripts\/sessions\.py\s+start\b/.test(command)) {
          recordWorktreeRouting(input.sessionID);
        }
      }
      if (READ_TOOLS.has(tool) || SEARCH_TOOLS.has(tool)) {
        const route = await resolveWorktreeRoute(client, input.sessionID, routingData || sessionsData());
        const routedOpenCodeSessionID = route.topLevelOpenCodeSessionID || input.sessionID;
        const files = explicitFilesForTest(toolArgs(input, output), route.worktreePath || instanceDirectory);
        runStaleRead("record", files, routedOpenCodeSessionID);
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
        runBridge("PostToolUse", bridgePayload("PostToolUse", tool, toolArgs(input, output), routedDirectory), routedOpenCodeSessionID, routedDirectory);
        runStaleRead("sync", files, routedOpenCodeSessionID);
      } finally {
        runEditLease("release", files, routedOpenCodeSessionID);
        markToolState(routedOpenCodeSessionID, [], true);
      }
    },
  };
};
