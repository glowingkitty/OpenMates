// frontend/packages/ui/src/services/projectState/projectFocusPolicy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Project focus send decisions of projectFocusSendPreflight.ts: the single Project a
// composer document mentions (structured mention nodes only) and the default focus a
// send activates. Network calls stay in the preflight service; with
// VITE_OPENMATES_RUST_CORE=1 the shared Rust core decides (web_projects/focus.rs).
// Refusals answer `{focusError: code}`; the page rethrows ProjectFocusSendPreflightError.

const PROJECT_MENTION_TYPES = new Set(["project", "project_folder", "project_file"]);
const PROJECT_MENTION_PREFIXES: Record<string, string> = {
  project: "@project:",
  project_folder: "@project-folder:",
  project_file: "@project-file:",
};

interface ComposerNode {
  type?: string;
  attrs?: Record<string, unknown>;
  content?: ComposerNode[];
}

export type FocusRefusal = { focusError: "MULTIPLE_PROJECTS" | "PROJECT_FOCUS_UNAVAILABLE" };

/**
 * Current composer consent for one Project. Only structured mention nodes qualify;
 * plaintext copied from message history cannot recreate this intent.
 */
export function projectFocusIntent(input: { document: unknown }):
  FocusRefusal | { intent: { projectId: string; source: "composer_project_mention" } | null } {
  const projectIds = new Set<string>();
  const visit = (node: ComposerNode): void => {
    if (node.type === "genericMention" && PROJECT_MENTION_TYPES.has(String(node.attrs?.mentionType ?? ""))) {
      const directProjectId = node.attrs?.projectId;
      if (typeof directProjectId === "string" && directProjectId.trim()) {
        projectIds.add(directProjectId.trim());
      } else {
        // Draft HTML rehydration can retain the structured Project mention and
        // canonical syntax while losing optional node-only attributes. Recover
        // only from that structured node; ordinary plaintext remains untrusted.
        const mentionType = String(node.attrs?.mentionType ?? "");
        const prefix = PROJECT_MENTION_PREFIXES[mentionType];
        const mentionSyntax = node.attrs?.mentionSyntax;
        if (prefix && typeof mentionSyntax === "string" && mentionSyntax.startsWith(prefix)) {
          const projectId = mentionSyntax.slice(prefix.length).split(":", 1)[0]?.trim();
          if (projectId) projectIds.add(projectId);
        }
      }
    }
    for (const child of node.content ?? []) visit(child);
  };
  const document = input.document;
  if (document && typeof document === "object") visit(document as ComposerNode);
  if (projectIds.size === 0) return { intent: null };
  if (projectIds.size > 1) return { focusError: "MULTIPLE_PROJECTS" };
  return { intent: { projectId: Array.from(projectIds)[0], source: "composer_project_mention" } };
}

/** The decrypted default focus a send activates (trimmed id and instructions). */
export function projectDefaultFocusRead(input: { settings: Record<string, unknown> }):
  FocusRefusal | { focus: { focus_id: string; instructions: string } } {
  const candidate = input.settings.default_focus;
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return { focusError: "PROJECT_FOCUS_UNAVAILABLE" };
  const focusId = (candidate as Record<string, unknown>).focus_id;
  const instructions = (candidate as Record<string, unknown>).instructions;
  if (typeof focusId !== "string" || !focusId.trim() || typeof instructions !== "string" || !instructions.trim()) {
    return { focusError: "PROJECT_FOCUS_UNAVAILABLE" };
  }
  return { focus: { focus_id: focusId.trim(), instructions: instructions.trim() } };
}

export const FOCUS_OPS = { projectFocusIntent, projectDefaultFocusRead };
