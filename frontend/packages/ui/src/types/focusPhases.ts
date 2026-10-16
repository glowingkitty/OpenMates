import { parseDocument } from "yaml";
import type { FocusPhaseDefinition } from "./apps";
// Shared wire contract and pure validation for phase history (never state authority).
export interface FocusPhaseEvent {
  type: "focus_phase_changed";
  event_id: string;
  chat_id: string;
  focus_id: string;
  run_id: string;
  version: number;
  phase_id: string;
  phase_title: string;
  direction: "forward" | "backward";
  created_at: number;
  project_id?: string;
}
export interface FocusPhaseState {
  schema_version: 1;
  chat_id: string;
  focus_id: string;
  run_id: string;
  revision: string;
  version: number;
  phase_id: string;
  complete: boolean;
  transitions: FocusPhaseEvent[];
}
export function parseFocusPhaseEvent(content: string): FocusPhaseEvent | null {
  try {
    const event = JSON.parse(content);
    if (event.type !== "focus_phase_changed" || typeof event.focus_id !== "string"
        || typeof event.phase_id !== "string" || typeof event.phase_title !== "string"
        || !event.phase_title.trim() || event.phase_title.length > 200
        || !["forward", "backward"].includes(event.direction)) return null;
    return event;
  } catch { return null; }
}
export function focusPhaseDetailsPath(event: FocusPhaseEvent): string | null {
  if (event.project_id && /^[a-f0-9-]{36}$/i.test(event.project_id)) return `projects/${event.project_id}`;
  const match = /^([a-z][a-z0-9_]*)-([a-z][a-z0-9_-]*)$/.exec(event.focus_id);
  return match ? `apps/${match[1]}/focus/${match[2]}` : null;
}

export function projectFocusPhases(instruction: unknown): FocusPhaseDefinition[] {
  if (typeof instruction !== "string" || !instruction.startsWith("---\n")) return [];
  const end = instruction.indexOf("\n---", 4);
  if (end < 0) return [];
  try {
    const document = parseDocument(instruction.slice(4, end), { uniqueKeys: true });
    if (document.errors.length) return [];
    const definition = document.toJS({ maxAliasCount: 0 });
    if (definition.phases_version !== 1 || !Array.isArray(definition.phases) || !definition.phases.length) return [];
    const ids = new Set();
    for (const phase of definition.phases) {
      if (!phase.id || ids.has(phase.id) || !phase.title || !phase.instructions || !Array.isArray(phase.requirements)
          || !phase.requirements.length || phase.requirements.some((r: {id?: string; text?: string}) => !r.id || !r.text)) return [];
      ids.add(phase.id);
    }
    return definition.phases;
  } catch { return []; }
}
