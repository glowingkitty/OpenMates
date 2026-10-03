import { describe, expect, it } from 'vitest';
import type { ProjectFolderViewModel, ProjectItemViewModel } from '../projectService';
import { compareProjectNames, projectChatFolderPath, projectRemoteBrowserRows, projectRemotePageReady } from '../projectChatBrowser';

function chat(name: string, metadata: Record<string, unknown> = {}, hash: string | null = null): ProjectItemViewModel {
  return { project_item_id: name, item_type: 'chat', target_id: `chat-${name}`, displayName: name, metadata,
    encrypted: { project_item_id: name, item_type: 'chat', target_id_hash: 'hash', target_id_encrypted: 'cipher', hashed_folder_id: hash, created_at: 1, updated_at: 1, position: 0 } };
}
const folders: ProjectFolderViewModel[] = [
  { folder_id: 'research', name: 'Research', parentHash: null, encrypted: { folder_id: 'research', hashed_project_id: 'project', encrypted_name: 'cipher', created_at: 1, updated_at: 1, position: 0 } },
  { folder_id: 'q4', name: 'Q4', parentHash: 'research-hash', encrypted: { folder_id: 'q4', hashed_project_id: 'project', encrypted_name: 'cipher', created_at: 1, updated_at: 1, position: 0 } },
];
const hashes = new Map([['research', 'research-hash'], ['q4', 'q4-hash']]);

describe('Project chat folders and mixed connected grids', () => {
  // contract-test: direct surface=gui.web assertions=projects.links.openmates-only-encrypted,projects.surface.semantic-parity
  it('keeps root links and explicit source paths isolated without filesystem access', () => {
    expect(projectChatFolderPath(chat('root'), 'source', folders, hashes)).toBe('.');
    expect(projectChatFolderPath(chat('source chat', { source_id: 'source', path: 'Research/Q4' }), 'source', folders, hashes)).toBe('Research/Q4');
    expect(projectChatFolderPath(chat('other', { source_id: 'other', path: 'Research' }), 'source', folders, hashes)).toBeNull();
    expect(projectChatFolderPath({ ...chat('file'), item_type: 'embed' }, 'source', folders, hashes)).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted,projects.surface.semantic-parity
  it('derives physical nested membership and honors a later move over stale metadata', () => {
    expect(projectChatFolderPath(chat('nested', { path: 'Old' }, 'q4-hash'), 'source', folders, hashes)).toBe('Research/Q4');
    expect(projectChatFolderPath(chat('missing', {}, 'missing'), 'source', folders, hashes)).toBeNull();
    expect(projectChatFolderPath(chat('cycle', {}, 'q4-hash'), 'source', [{ ...folders[0], parentHash: 'q4-hash' }, folders[1]], hashes)).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted,projects.surface.semantic-parity
  it.each(['../private', '/private', 'a/../b', 'a//b', 'a\\b', 'a/./b', 42])('rejects invalid encrypted folder path %s', (path) => {
    expect(projectChatFolderPath(chat('unsafe', { path }), 'source', folders, hashes)).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted,projects.surface.semantic-parity
  it('keeps intermediate folders reachable while offline and deduplicates live directories', () => {
    const values = [chat('Research discussion', {}, 'q4-hash')];
    const rows = (path: string) => projectRemoteBrowserRows(values, folders, hashes, 'source', path, []);
    expect(rows('.').map((row) => row.name)).toEqual(['Research']);
    expect(rows('Research').map((row) => row.name)).toEqual(['Q4']);
    expect(rows('Research/Q4').map((row) => row.kind)).toEqual(['chat']);
    expect(projectRemoteBrowserRows(values, folders, hashes, 'source', '.', [{ path: 'Research', kind: 'directory' }]).map((row) => row.kind)).toEqual(['remote']);
    expect(projectRemoteBrowserRows(values, folders, hashes, 'source', '.', [{ path: 'Research', kind: 'file' }]).map((row) => row.kind)).toEqual(['chat-folder', 'remote']);
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted,projects.surface.semantic-parity
  it('interleaves files, folders and chats with deterministic equal-name ordering', () => {
    const values = [chat('B'), chat('A'), chat('z')];
    const rows = projectRemoteBrowserRows(values, folders, hashes, 'source', '.', [{ path: 'B', kind: 'file' }, { path: 'C', kind: 'directory' }]);
    expect(rows.map((row) => row.name)).toEqual(['A', 'B', 'B', 'C', 'z']);
    expect(rows.filter((row) => row.name === 'B').map((row) => row.kind)).toEqual(['chat', 'remote']);
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted,projects.surface.semantic-parity
  it('fills mixed pages across server cursor boundaries without missing or duplicate rows', () => {
    const files = Array.from({ length: 130 }, (_, i) => ({ path: `file-${String(i).padStart(3, '0')}`, kind: 'file' as const }));
    const values = [chat('A'), chat('file-047'), chat('file-048'), chat('z-last'), chat('deep', { path: 'file-125/deeper' })];
    const all = projectRemoteBrowserRows(values, folders, hashes, 'source', '.', files);
    const seen: string[] = [];
    let fetched = 0;
    for (let page = 0; page < 3; page++) {
      let rows = projectRemoteBrowserRows(values, folders, hashes, 'source', '.', files.slice(0, fetched));
      let cursor = fetched && fetched < files.length ? files[fetched - 1].path : null;
      while (!fetched || !projectRemotePageReady(rows, page, 48, cursor)) {
        fetched = Math.min(files.length, fetched + 48);
        rows = projectRemoteBrowserRows(values, folders, hashes, 'source', '.', files.slice(0, fetched));
        cursor = fetched < files.length ? files[fetched - 1].path : null;
      }
      seen.push(...rows.slice(page * 48, (page + 1) * 48).map((row) => row.key));
    }
    expect(seen).toEqual(all.map((row) => row.key));
    expect(new Set(seen).size).toBe(all.length);
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted,projects.surface.semantic-parity
  it('does not consider a late chat safe before unfetched earlier file names', () => {
    const rows = projectRemoteBrowserRows([chat('z')], [], new Map(), 'source', '.', []);
    expect(projectRemotePageReady(rows, 0, 1, 'a')).toBe(false);
    expect(projectRemotePageReady(rows, 0, 1, null)).toBe(true);
    expect(compareProjectNames('e', 'é')).not.toBe(0);
  });
});
