// .opencode/plugins/openmates-claude-hooks.js
// Reuses the existing Claude Code hook scripts from OpenCode without moving
// or replacing the Claude-specific setup.

const { spawnSync } = require("child_process")
const path = require("path")

const PROJECT_ROOT = "/home/superdev/projects/OpenMates"
const HOOK_DIR = path.join(PROJECT_ROOT, ".claude", "hooks")

const BASH_PRE_HOOKS = ["bash-guard.sh"]

const EDIT_PRE_HOOKS = [
  "pre-edit-guard.sh",
  "provider-registry-sync.sh",
  "analytics-sdk-forbidden.sh",
  "legal-text-lastupdated-bump.sh",
  "pii-logger-guard.sh",
  "privacy-promise-guard.sh",
  "cli-credential-prompt-guard.sh",
  "external-resources-guard.sh",
  "cookie-consent-gate.sh",
  "css-selector-in-specs.sh",
  "svelte5-legacy-syntax.sh",
  "donation-language-guard.sh",
  "settings-canonical-elements.sh",
  "e2e-encryption-guard.sh",
]

const EDIT_POST_HOOKS = [
  "auto-track.sh",
  "auto-rebuild-translations.sh",
  "testid-drift-detector.sh",
  "encryption-architecture-reminder.sh",
]

const SESSION_START_HOOKS = ["tdd-session-context.sh"]
const SESSION_IDLE_HOOKS = ["check-uncommitted.sh"]

function normalizeToolName(tool) {
  return String(tool || "").toLowerCase()
}

function isBashTool(tool) {
  return ["bash", "shell"].includes(normalizeToolName(tool))
}

function isEditTool(tool) {
  const name = normalizeToolName(tool)
  return ["edit", "write", "patch", "apply_patch"].includes(name)
}

function filePathFromArgs(args) {
  return args?.filePath || args?.file_path || args?.path || ""
}

function commandFromArgs(args) {
  return args?.command || args?.cmd || ""
}

function claudePayload(eventName, tool, args, extra = {}) {
  const toolInput = { ...(args || {}) }
  const filePath = filePathFromArgs(args)
  const command = commandFromArgs(args)

  if (filePath) toolInput.file_path = filePath
  if (command) toolInput.command = command

  return {
    cwd: PROJECT_ROOT,
    hook_event_name: eventName,
    tool_name: tool,
    tool_input: toolInput,
    ...extra,
  }
}

function parseHookMessage(text) {
  const trimmed = String(text || "").trim()
  if (!trimmed) return ""

  try {
    const parsed = JSON.parse(trimmed)
    return (
      parsed.reason ||
      parsed.stopReason ||
      parsed.systemMessage ||
      parsed.hookSpecificOutput?.permissionDecisionReason ||
      parsed.hookSpecificOutput?.additionalContext ||
      trimmed
    )
  } catch (_) {
    return trimmed
  }
}

function runHook(script, payload, { blockOnFailure = true } = {}) {
  const result = spawnSync(path.join(HOOK_DIR, script), {
    cwd: PROJECT_ROOT,
    input: JSON.stringify(payload),
    encoding: "utf8",
    timeout: 30000,
    env: {
      ...process.env,
      PROJECT_ROOT,
    },
  })

  if (result.error) {
    if (blockOnFailure) throw result.error
    return
  }

  if (result.status === 2) {
    throw new Error(parseHookMessage(result.stderr || result.stdout) || `${script} blocked this action`)
  }

  if (blockOnFailure && result.status && result.status !== 0) {
    throw new Error(parseHookMessage(result.stderr || result.stdout) || `${script} failed`)
  }
}

function runHooks(scripts, payload, options) {
  for (const script of scripts) runHook(script, payload, options)
}

exports.OpenMatesClaudeHooks = async () => {
  return {
    "tool.execute.before": async (input, output) => {
      const tool = input.tool
      const args = output.args || {}

      if (isBashTool(tool)) {
        runHooks(BASH_PRE_HOOKS, claudePayload("PreToolUse", "Bash", args), { blockOnFailure: true })
        return
      }

      if (isEditTool(tool)) {
        runHooks(EDIT_PRE_HOOKS, claudePayload("PreToolUse", "Edit", args), { blockOnFailure: true })
      }
    },

    "tool.execute.after": async (input, output) => {
      if (!isEditTool(input.tool)) return

      runHooks(
        EDIT_POST_HOOKS,
        claudePayload("PostToolUse", "Edit", output.args || {}, { tool_response: output.result || null }),
        { blockOnFailure: false },
      )
    },

    event: async ({ event }) => {
      if (event.type === "session.created") {
        runHooks(SESSION_START_HOOKS, { cwd: PROJECT_ROOT, hook_event_name: "SessionStart", source: "startup" }, { blockOnFailure: false })
      }

      if (event.type === "session.idle") {
        runHooks(SESSION_IDLE_HOOKS, { cwd: PROJECT_ROOT, hook_event_name: "Stop", stop_hook_active: false }, { blockOnFailure: false })
      }
    },
  }
}
