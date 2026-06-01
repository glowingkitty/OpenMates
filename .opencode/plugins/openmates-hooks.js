// OpenMates OpenCode hook bridge.
//
// Keeps OpenCode policy enforcement aligned with Claude/Codex without
// duplicating the individual hook scripts. Tool events are translated into the
// same payload shape consumed by the Codex Claude-hook bridge, which then runs
// the canonical hooks from `.claude/hooks/`.

import { spawnSync } from "node:child_process";

const EDIT_TOOLS = new Set(["apply_patch", "edit", "write", "Edit", "Write"]);
const PROJECT_ROOT = "/home/superdev/projects/OpenMates";
const BRIDGE = `${PROJECT_ROOT}/.codex/hooks/claude-hook-bridge.sh`;
const POST_EDIT_LINTS = [
  `${PROJECT_ROOT}/scripts/lint-design-tokens.sh`,
  `${PROJECT_ROOT}/scripts/lint-swift-design-tokens.sh`,
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
      if (tool !== "bash" && tool !== "Bash" && !EDIT_TOOLS.has(tool)) return;

      runBridge("PreToolUse", bridgePayload("PreToolUse", tool, output?.args));
    },
    "tool.execute.after": async (input, output) => {
      const tool = input.tool || "";
      if (!EDIT_TOOLS.has(tool)) return;

      const args = output?.args;
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
