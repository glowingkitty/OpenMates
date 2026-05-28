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

function bridgePayload(event, tool, args) {
  return {
    cwd: PROJECT_ROOT,
    hook_event_name: event,
    tool_name: normalizeToolName(tool),
    tool_input: toolInput(args),
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

      runBridge("PostToolUse", bridgePayload("PostToolUse", tool, output?.args));
    },
  };
};
