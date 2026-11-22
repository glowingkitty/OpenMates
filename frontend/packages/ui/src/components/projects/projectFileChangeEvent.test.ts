import { describe, expect, it } from 'vitest';
import { readProjectFileChangeRows, withLiveDiffs } from './projectFileChangeEvent';
import type { ProjectFileApprovalEntry } from '../../stores/projectFileApprovalStore';

const base = 'a'.repeat(64);
const applied = (projectId: string, path: string, patch: string) => ({ id: path, kind: 'write', status: 'applied',
  request: { projectId, chatId: 'c', mutation: { operation: 'update_file', operation_id: path, path, expected_base: base, patch } } }) as ProjectFileApprovalEntry;

describe('projects/change event rows', () => {
  // contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
  it('reads valid rows, defaults the action and drops incomplete or malformed fields', () => {
    expect(readProjectFileChangeRows({ results: [
      { project_id: 'p', path: 'a.ts', action: 'created', project_name: 'App', expected_base: base, team_id: 't' },
      { project_id: 'p', path: 'b.ts', action: 'weird', expected_base: 'short' },
      { project_id: 'p', path: 'c.ts', action: 'renamed', from_path: 'old.ts' },
      { path: 'no-project.ts' }, 'junk',
    ] })).toEqual([
      { project_id: 'p', path: 'a.ts', action: 'created', project_name: 'App', expected_base: base, team_id: 't' },
      { project_id: 'p', path: 'b.ts', action: 'updated' },
      { project_id: 'p', path: 'c.ts', action: 'renamed', from_path: 'old.ts' },
    ]);
    expect(readProjectFileChangeRows(undefined)).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
  it('attaches the live diff only for the same project and path', () => {
    const rows = readProjectFileChangeRows({ results: [
      { project_id: 'p', path: 'a.ts', action: 'updated' }, { project_id: 'other', path: 'a.ts', action: 'updated' } ] });
    const items = withLiveDiffs(rows, [applied('p', 'a.ts', '+new')]);
    expect(items[0].diff).toBe('+new');
    expect(items[1].diff).toBeUndefined();
  });
});
