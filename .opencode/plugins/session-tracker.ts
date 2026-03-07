/**
 * OpenMates Session Tracker Plugin
 *
 * Purpose: Automates concurrent session coordination for multi-agent workflows.
 *   - Tracks files modified via edit/write tools into .claude/sessions.json
 *   - Blocks writes when another session holds an exclusive file lock
 *
 * Architecture context: See docs/claude/concurrent-sessions.md
 * Replaces: .claude/settings.json hooks (Claude Code only — ignored by OpenCode)
 *
 * Events used:
 *   tool.execute.before — check write lock before edit/write; block if locked
 *   tool.execute.after  — record modified file to session's modified_files list
 *
 * Note: session start/end are NOT automated here because Claude needs to supply
 * a task description. See CLAUDE.md "Session Coordination" for the manual steps.
 */

import type { Plugin } from "@opencode-ai/plugin";

export const SessionTracker: Plugin = async ({ $, directory }) => {
  // Resolve path to sessions.py relative to project root (where plugin runs)
  const sessionsPy = `${directory}/scripts/sessions.py`;

  return {
    /**
     * Before any edit/write tool — check if another session has claimed the file.
     * Throws an error to block the operation if so (same semantics as exit 2 in hooks).
     */
    "tool.execute.before": async (input, output) => {
      const tool = input.tool as string;
      if (tool !== "edit" && tool !== "write") return;

      const filePath = (output.args as Record<string, unknown>)?.filePath as
        | string
        | undefined;
      if (!filePath) return;

      try {
        // Exit 2 means blocked; exit 0 means allowed
        const result =
          await $`python3 ${sessionsPy} check-write --file ${filePath}`.quiet();
        if (result.exitCode === 2) {
          // Read stderr for the human-readable block message
          const msg =
            result.stderr?.toString().trim() ||
            `File '${filePath}' is locked by another session.`;
          throw new Error(msg);
        }
      } catch (err: unknown) {
        // Re-throw if it's a blocking error from us; ignore if sessions.py is missing/broken
        if (err instanceof Error && err.message.includes("locked by"))
          throw err;
        if (
          err instanceof Error &&
          err.message.includes("is currently being written")
        )
          throw err;
        // Otherwise (e.g. python not found, file not found) — allow the write silently
      }
    },

    /**
     * After any edit/write tool completes — record the modified file path into
     * the most-recently-active session's modified_files list. This is async and
     * non-blocking; the agent does not wait for it.
     */
    "tool.execute.after": async (input) => {
      const tool = input.tool as string;
      if (tool !== "edit" && tool !== "write") return;

      const filePath = (input.args as Record<string, unknown>)?.filePath as
        | string
        | undefined;
      if (!filePath) return;

      try {
        await $`python3 ${sessionsPy} track --file ${filePath}`.quiet();
      } catch {
        // Non-critical — silently ignore failures (e.g. no active session)
      }
    },
  };
};
