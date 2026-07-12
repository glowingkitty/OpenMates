// OpenMates OpenCode hook bridge.
//
// Keeps OpenCode policy enforcement aligned with Claude/Codex without
// duplicating the individual hook scripts. Tool events are translated into the
// same payload shape consumed by the Codex Claude-hook bridge, which then runs
// the canonical hooks from `.claude/hooks/`.

import { spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";

const EDIT_TOOLS = new Set(["apply_patch", "edit", "write", "Edit", "Write"]);
const BASH_TOOLS = new Set(["bash", "Bash"]);
const READ_TOOLS = new Set(["read", "Read"]);
const PROJECT_ROOT = "/home/superdev/projects/OpenMates";
const LEASE_SWEEP_INTERVAL_MS = 30_000;
const LEASE_HEARTBEAT_INTERVAL_MS = 60_000;
const BRIDGE = `${PROJECT_ROOT}/.codex/hooks/claude-hook-bridge.sh`;
const POST_EDIT_LINTS = [
  `${PROJECT_ROOT}/scripts/lint-design-tokens.sh`,
  `${PROJECT_ROOT}/scripts/lint-swift-design-tokens.sh`,
];
const POST_EDIT_AUDITS = [
  ["python3", `${PROJECT_ROOT}/scripts/audit_apple_release_preflight.py`, "--hook"],
  ["python3", `${PROJECT_ROOT}/scripts/audit_ui_control_visibility.py`, "--hook"],
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

function defaultRunLease(command, sessionID, files = [], generation) {
  const args = [`${PROJECT_ROOT}/scripts/opencode_file_leases.py`, command];
  if (sessionID) args.push("--session", sessionID);
  if (files.length) args.push("--files", ...files);
  if (generation !== undefined) args.push("--generation", String(generation));
  const result = spawnSync("python3", args, {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
  });
  const stdout = (result.stdout || "").trim();
  if (result.status !== 0 && result.status !== 2) {
    throw new Error((result.stderr || stdout || `File lease ${command} failed`).trim());
  }
  return stdout ? JSON.parse(stdout) : {};
}

function defaultHasActiveBinding(sessionID) {
  const result = spawnSync("python3", [`${PROJECT_ROOT}/scripts/sessions.py`, "status", "--json"], {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
  });
  if (result.status !== 0) return true;
  const state = JSON.parse(result.stdout || "{}");
  return Object.values(state.sessions || {}).some((session) => session.opencode_session_id === sessionID);
}

export function createFileLeaseCoordinator({
  client,
  runLease = defaultRunLease,
  hasActiveBinding = defaultHasActiveBinding,
}) {
  const lastHeartbeat = new Map();
  const activeEdits = new Map();
  const deliveringNotifications = new Set();
  const notifierID = `opencode-${randomUUID()}`;

  function beginEdit(sessionID, files) {
    const active = activeEdits.get(sessionID) || [];
    const requested = new Set(files);
    if (active.some((edit) => edit.files.some((file) => requested.has(file)))) {
      throw new Error("An overlapping edit is already in flight for this OpenCode chat; retry after it completes.");
    }
    active.push({ files });
    activeEdits.set(sessionID, active);
  }

  function finishEdit(sessionID, files) {
    const active = activeEdits.get(sessionID) || [];
    const completed = new Set(files);
    const index = active.findIndex(
      (edit) => edit.files.length === completed.size && edit.files.every((file) => completed.has(file)),
    );
    if (index !== -1) active.splice(index, 1);
    if (active.length === 0) {
      activeEdits.delete(sessionID);
      return;
    }
    activeEdits.set(sessionID, active);
  }

  async function notifyGrants() {
    const claimed = await runLease("claim", notifierID, []);
    for (const grant of claimed?.notifications || []) {
      const notificationKey = `${grant.session_id}:${grant.generation}`;
      if (deliveringNotifications.has(notificationKey)) continue;
      deliveringNotifications.add(notificationKey);
      try {
        const messageID = `msg_${createHash("sha256").update(`file-lease:${notificationKey}`).digest("hex").slice(0, 26)}`;
        await client.session.prompt({
          path: { id: grant.session_id },
          body: {
            messageID,
            parts: [{
              type: "text",
              text: `Your requested file lease is now available for: ${grant.files.join(", ")}. Resume the blocked edit step now.`,
            }],
          },
        });
        await runLease("acknowledge", grant.session_id, [], grant.generation);
      } catch (error) {
        console.error(`[opencode-file-leases] grant notification failed session=${grant.session_id}`, error);
      } finally {
        deliveringNotifications.delete(notificationKey);
      }
    }
  }

  return {
    prepareCommand(input, output) {
      const command = bashCommand(output?.args || input?.args);
      if (!input?.sessionID || !/python3\s+scripts\/sessions\.py\s+start\b/.test(command)) return;
      if (/--opencode-session\b/.test(command) || /[;&|]/.test(command)) return;
      output.args.command = `${command} --opencode-session ${input.sessionID}`;
    },
    async heartbeat(sessionID) {
      if (!sessionID) return;
      const now = Date.now();
      if (now - (lastHeartbeat.get(sessionID) || 0) < LEASE_HEARTBEAT_INTERVAL_MS) return;
      lastHeartbeat.set(sessionID, now);
      await runLease("heartbeat", sessionID, []);
      await notifyGrants();
    },
    async beforeEdit(sessionID, files) {
      const requestedFiles = [...new Set(files)].sort();
      if (!sessionID || requestedFiles.length === 0) return;
      beginEdit(sessionID, requestedFiles);
      try {
        const result = await runLease("acquire", sessionID, requestedFiles);
        if (result.status === "waiting") {
          throw new Error(
            `Waiting for file lease (queue position ${result.position}): ${result.files.join(", ")}. ` +
            "Do not end the task; this chat will be resumed automatically after the complete file set is granted.",
          );
        }
        const authorization = await runLease("authorize", sessionID, requestedFiles, result.generation);
        if (!authorization.authorized) {
          throw new Error(`File lease generation ${result.generation} is no longer valid; retry the edit acquisition.`);
        }
      } catch (error) {
        finishEdit(sessionID, requestedFiles);
        throw error;
      }
    },
    afterEdit(sessionID, files) {
      finishEdit(sessionID, [...new Set(files)].sort());
    },
    guardBash(command) {
      const repositoryMutation = /\bgit\s+apply\b/.test(command);
      const directMutation = /\b(?:sed\s+-i|perl\s+-pi|tee|touch|cp|mv|rm|truncate|install|rsync|patch|dd)\b/.test(command)
        || />>?/.test(command)
        || /\b(?:python3?|node)\b.*\b(?:open|write_text|write_bytes|writeFile(?:Sync)?|appendFile(?:Sync)?)\s*\(/.test(command);
      const repositorySource = /(?:^|[\s"'(])(?:frontend|backend|scripts|docs|apple|\.opencode|\.claude)\//.test(command)
        || /\.(?:py|js|mjs|ts|tsx|svelte|swift|md|ya?ml|json)(?:[\s"',)]|$)/.test(command);
      if (repositoryMutation || (directMutation && repositorySource)) {
        throw new Error("Use apply_patch for source-file changes so the file lease can be acquired and verified.");
      }
    },
    async afterCommand(sessionID, command, outputText) {
      if (!sessionID) return;
      const ended = /python3\s+scripts\/sessions\.py\s+(?:end\b|deploy\b.*--end\b)/.test(command)
        && /Session [a-f0-9]+ ended and removed/i.test(outputText);
      if (ended && !await hasActiveBinding(sessionID)) {
        await runLease("release", sessionID, []);
        await notifyGrants();
      }
    },
    async sweep() {
      for (const [sessionID, active] of activeEdits) {
        if (active.length === 0) continue;
        await runLease("heartbeat", sessionID, []);
      }
      await runLease("sweep", "", []);
      await notifyGrants();
    },
    setShellEnvironment(input, output) {
      if (!input?.sessionID) return;
      output.env ||= {};
      output.env.OPENCODE_SESSION_ID = input.sessionID;
    },
  };
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

  if (result.status !== 0) {
    throw new Error(stderr || stdout || `OpenMates hook bridge failed with exit ${result.status}`);
  }
}

function runCommand(command, payload) {
  const result = spawnSync("bash", ["-lc", command], {
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

function runCommandArgs(command, args, payload, allowHookWarning = false) {
  const result = spawnSync(command, args, {
    cwd: PROJECT_ROOT,
    input: JSON.stringify(payload),
    encoding: "utf8",
  });

  const stdout = (result.stdout || "").trim();
  const stderr = (result.stderr || "").trim();

  if (stdout) console.log(stdout);
  if (stderr) console.error(stderr);

  if (result.status !== 0 && !(allowHookWarning && result.status === 2)) {
    throw new Error(stderr || stdout || `OpenMates command hook failed with exit ${result.status}`);
  }
}

function runStaleRead(action, sessionID, file) {
  if (!sessionID || !file) return;

  const result = spawnSync("python3", [
    `${PROJECT_ROOT}/scripts/sessions.py`,
    "stale-read",
    action,
    "--opencode-session",
    sessionID,
    "--file",
    file,
  ], {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
  });
  const stdout = (result.stdout || "").trim();
  const stderr = (result.stderr || "").trim();
  if (stdout) console.log(stdout);
  if (stderr) console.error(stderr);
  if (result.status !== 0) {
    throw new Error(stderr || stdout || `OpenCode stale-read ${action} failed with exit ${result.status}`);
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

export const OpenMatesHooks = async ({ client, runLease, hasActiveBinding, runHookBridge = runBridge }) => {
  const fileLeases = createFileLeaseCoordinator({ client, runLease, hasActiveBinding });
  const sweepTimer = setInterval(() => {
    fileLeases.sweep().catch((error) => console.error("[opencode-file-leases] sweep failed", error));
  }, LEASE_SWEEP_INTERVAL_MS);
  sweepTimer.unref?.();

  return {
    "shell.env": async (input, output) => {
      fileLeases.setShellEnvironment(input, output);
    },
    "tool.execute.before": async (input, output) => {
      const tool = input.tool || "";
      if (!BASH_TOOLS.has(tool) && !EDIT_TOOLS.has(tool) && !READ_TOOLS.has(tool)) return;

      if (BASH_TOOLS.has(tool)) {
        fileLeases.guardBash(bashCommand(output?.args || input?.args));
      }
      fileLeases.prepareCommand(input, output);
      await fileLeases.heartbeat(input.sessionID);

      if (EDIT_TOOLS.has(tool)) {
        const files = editedFiles(input?.args || output?.args);
        for (const file of files) {
          runStaleRead("check", input.sessionID, file);
        }
        runHookBridge("PreToolUse", bridgePayload("PreToolUse", tool, output?.args), input.sessionID);
        await fileLeases.beforeEdit(input.sessionID, files);
      } else if (!READ_TOOLS.has(tool)) {
        runHookBridge("PreToolUse", bridgePayload("PreToolUse", tool, output?.args), input.sessionID);
      }
    },
    "tool.execute.after": async (input, output) => {
      const tool = input.tool || "";
      if (BASH_TOOLS.has(tool)) {
        const command = bashCommand(toolArgs(input, output));
        await fileLeases.afterCommand(input.sessionID, command, output?.output || "");
        if (isCliAuthFailure(command, output?.output || "")) {
          appendCliLoginHint(output);
        }
      }

      if (READ_TOOLS.has(tool)) {
        const args = input?.args || {};
        const file = args.filePath || args.file_path || args.path;
        runStaleRead("record", input.sessionID, file);
        return;
      }

      if (!EDIT_TOOLS.has(tool)) return;

      const args = input?.args || toolArgs(input, output);
      fileLeases.afterEdit(input.sessionID, editedFiles(args));
      runBridge("PostToolUse", bridgePayload("PostToolUse", tool, args), input.sessionID);

      for (const file of editedFiles(args)) {
        const payload = filePayload("PostToolUse", file);
        for (const command of POST_EDIT_LINTS) {
          runCommand(command, payload);
        }
        for (const [command, ...commandArgs] of POST_EDIT_AUDITS) {
          runCommandArgs(
            command,
            [...commandArgs, file],
            payload,
            commandArgs[0]?.endsWith("audit_ui_control_visibility.py"),
          );
        }
        runStaleRead("sync", input.sessionID, file);
      }
    },
  };
};
