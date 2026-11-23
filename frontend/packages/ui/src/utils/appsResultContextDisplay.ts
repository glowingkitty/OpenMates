/** Separator between a user's own words and the result data an Apps
 * "ask in chat" handoff appends for the assistant (issue S6BEV). */
export const APPS_RESULT_CONTEXT_MARKER = "\n\nResult context (data supplied by the user):\n";

/** User bubbles show only what the user wrote. The stored, encrypted message
 * and what the assistant receives keep the full result context unchanged. */
export function appsResultContextDisplayText(content: string, role: string): string {
  if (role !== "user") return content;
  const index = content.indexOf(APPS_RESULT_CONTEXT_MARKER);
  return index < 0 ? content : content.slice(0, index).trimEnd();
}
