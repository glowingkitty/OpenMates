// frontend/packages/ui/src/components/projects/projectCreatedEvent.ts
// Reads the "assistant created a Project" marker from an assistant message. The server writes it
// into the focus activation embed reference (project_created, project_id, project_name); the chat
// history shows it as a system event row before the reply. Pure read, no persisted message type.

export interface ProjectCreatedEventData {
  projectId: string;
  projectName: string;
}

const JSON_BLOCK = /```json\n([\s\S]*?)\n```/g;

/** The created-Project marker of an assistant message, or null when it has none. */
export function readProjectCreatedEvent(content: unknown): ProjectCreatedEventData | null {
  if (typeof content !== 'string' || !content.includes('project_created')) return null;
  for (const match of content.matchAll(JSON_BLOCK)) {
    let ref: Record<string, unknown>;
    try {
      ref = JSON.parse(match[1].trim()) as Record<string, unknown>;
    } catch {
      continue; // Not an embed reference: ordinary JSON code block.
    }
    if (ref.type === 'focus_mode_activation' && ref.project_created === true
      && typeof ref.project_id === 'string' && ref.project_id
      && typeof ref.project_name === 'string' && ref.project_name) {
      return { projectId: ref.project_id, projectName: ref.project_name };
    }
  }
  return null;
}
