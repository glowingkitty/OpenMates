/** Maps a projects/change skill embed (references only, never file content) to chat-history event rows. */
import type { ProjectFileApprovalEntry } from '../../stores/projectFileApprovalStore';

export type ProjectFileChangeAction = 'created' | 'updated' | 'deleted' | 'renamed';
export interface ProjectFileChangeRow {
  project_id: string; project_name?: string; path: string; action: ProjectFileChangeAction;
  from_path?: string; expected_base?: string; team_id?: string;
}
export interface ProjectFileChangeItem extends ProjectFileChangeRow { diff?: string }

const ACTIONS = new Set<string>(['created', 'updated', 'deleted', 'renamed']);
const text = (value: unknown): string | undefined => typeof value === 'string' && value.trim() ? value.trim() : undefined;

/** Reads the change rows of a decoded embed; rows without a project id or path are dropped. */
export function readProjectFileChangeRows(content: unknown): ProjectFileChangeRow[] {
  const results = (content as { results?: unknown } | null)?.results;
  if (!Array.isArray(results)) return [];
  return results.flatMap((value): ProjectFileChangeRow[] => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
    const row = value as Record<string, unknown>;
    const projectId = text(row.project_id);
    const path = text(row.path);
    if (!projectId || !path) return [];
    const action = ACTIONS.has(String(row.action)) ? row.action as ProjectFileChangeAction : 'updated';
    const base = text(row.expected_base);
    return [{ project_id: projectId, path, action,
      ...(text(row.project_name) ? { project_name: text(row.project_name) } : {}),
      ...(text(row.from_path) ? { from_path: text(row.from_path) } : {}),
      ...(base && /^[a-f0-9]{64}$/.test(base) ? { expected_base: base } : {}),
      ...(text(row.team_id) ? { team_id: text(row.team_id) } : {}) }];
  });
}

/** Attaches the live in-memory diff (applied this session) for the same project and path. */
export function withLiveDiffs(rows: ProjectFileChangeRow[], entries: ProjectFileApprovalEntry[]): ProjectFileChangeItem[] {
  return rows.map((row) => {
    const entry = [...entries].reverse().find((candidate) => candidate.kind === 'write' && candidate.status === 'applied'
      && candidate.request.projectId === row.project_id && candidate.request.mutation.path === row.path);
    if (!entry || entry.kind !== 'write') return row;
    const mutation = entry.request.mutation;
    const diff = mutation.patch ?? mutation.content;
    return diff ? { ...row, diff } : row;
  });
}
