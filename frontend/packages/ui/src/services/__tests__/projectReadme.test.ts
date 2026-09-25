import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProjectItemViewModel, ProjectSourceViewModel, ProjectViewModel } from '../projectService';

const mocks = vi.hoisted(() => ({
  readEncryptedProjectFile: vi.fn(),
  requestProjectRemoteAccess: vi.fn(),
  fetchAndDecryptImage: vi.fn(),
}));

vi.mock('../projectService', () => ({
  readEncryptedProjectFile: mocks.readEncryptedProjectFile,
  requestProjectRemoteAccess: mocks.requestProjectRemoteAccess,
}));
vi.mock('../../components/embeds/images/imageEmbedCrypto', () => ({
  fetchAndDecryptImage: mocks.fetchAndDecryptImage,
}));
vi.mock('../../utils/imageProxy', () => ({
  MAX_WIDTH_CONTENT_IMAGE: 800,
  proxyImage: (url: string, width: number) => `/image-proxy?url=${encodeURIComponent(url)}&width=${width}`,
}));

import {
  findStoredProjectReadme,
  loadProjectReadme,
  projectReadmeImageSources,
  projectReadmeText,
  safeProjectReadmeImageUrl,
} from '../projectReadme';

const project = {
  project_id: 'project-1', name: 'Project', description: '', icon: 'folder', projectKey: new Uint8Array(32),
  encrypted: { project_id: 'project-1', encrypted_project_key: 'key', encrypted_name: 'name', created_at: 1, updated_at: 1, last_opened_at: 1 },
} satisfies ProjectViewModel;

function item(name: string, path?: string): ProjectItemViewModel {
  return {
    project_item_id: `item-${name}`, item_type: 'embed', target_id: `embed-${name}`,
    displayName: name, metadata: path ? { source: 'hosted_project_file', path } : {},
    encrypted: { project_item_id: `item-${name}`, item_type: 'embed', target_id_hash: 'hash', target_id_encrypted: 'cipher', created_at: 1, updated_at: 1, position: 1 },
  };
}

const source = {
  source_id: 'source-1', source_type: 'local_git_repository', displayName: 'Repo', metadata: {},
  capabilities: ['read'], status: 'connected', sourceSessionId: 'session-1', keyEpoch: 1,
  encrypted: { source_id: 'source-1', source_type: 'local_git_repository', encrypted_display_name: 'name', encrypted_metadata: 'meta', capabilities: ['read'], status: 'connected', created_at: 1, updated_at: 1 },
} satisfies ProjectSourceViewModel;

describe('project README loading', () => {
  beforeEach(() => vi.clearAllMocks());

  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted,projects.surface.semantic-parity
  it('finds only a root README and supports legacy markdown content fields', () => {
    expect(findStoredProjectReadme([item('README.md', 'docs/README.md'), item('readme.MD')])?.displayName).toBe('readme.MD');
    expect(findStoredProjectReadme([item('README.md', 'docs/README.md')])).toBeNull();
    const nestedRemoteReadme = item('README.md');
    nestedRemoteReadme.metadata = { imported_from_remote_source: true, remote_path: 'docs/README.md' };
    expect(findStoredProjectReadme([nestedRemoteReadme])).toBeNull();
    expect(projectReadmeText({ markdown: '# Legacy upload' })).toBe('# Legacy upload');
    expect(projectReadmeText({ filename: 'README.md' })).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
  it('chooses the newest root README when an upload replaces an older file', () => {
    const older = item('README.md');
    older.encrypted.created_at = 1;
    older.encrypted.updated_at = 1;
    const newer = item('readme.md');
    newer.encrypted.created_at = 2;
    newer.encrypted.updated_at = 2;
    expect(findStoredProjectReadme([older, newer])?.target_id).toBe(newer.target_id);
    expect(findStoredProjectReadme([newer, older])?.target_id).toBe(newer.target_id);

    older.encrypted.created_at = newer.encrypted.created_at;
    older.encrypted.updated_at = newer.encrypted.updated_at;
    older.metadata.readme_uploaded_at_ms = 1000;
    newer.metadata.readme_uploaded_at_ms = 1001;
    expect(findStoredProjectReadme([older, newer])?.target_id).toBe(newer.target_id);
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.no-server-decryption-authority,projects.surface.semantic-parity
  it('proxies public images and rejects executable or internal network URLs', () => {
    expect(safeProjectReadmeImageUrl('https://cdn.example.test/a.png')).toContain('/image-proxy?');
    expect(safeProjectReadmeImageUrl('javascript:alert(1)')).toBeNull();
    expect(safeProjectReadmeImageUrl('data:image/png;base64,AAAA')).toBeNull();
    expect(safeProjectReadmeImageUrl('../private.png')).toBeNull();
    expect(projectReadmeImageSources(
      '![one](a.png) ![two](<docs/b.png> "Title")\n![Diagram][ARCH]\n\n[arch]: docs/architecture.png "Architecture"',
    )).toEqual(['a.png', 'docs/b.png', 'docs/architecture.png']);
  });

  // contract-test: supporting surface=gui.web assertions=projects.uploads.project-wrapped,projects.files.no-server-decryption-authority
  it('renders the inline code payload used by a newly uploaded root README and resolves its encrypted image item', async () => {
    const readme = item('README.md');
    const image = item('diagram.png', 'docs/diagram.png');
    mocks.readEncryptedProjectFile
      .mockResolvedValueOnce({ content: { code: '# Hello\n![Diagram](docs/diagram.png)' }, revision: 1 })
      .mockResolvedValueOnce({ content: { data_url: 'data:image/png;base64,AAAA' }, revision: 1 });

    const result = await loadProjectReadme({ project, items: [readme, image], sources: [source], remoteContext: { ownerId: 'user-1' } });

    expect(result.status).toBe('ready');
    if (result.status === 'ready') {
      expect(result.document.origin).toBe('stored');
      expect(result.document.imageUrls['docs/diagram.png']).toBe('data:image/png;base64,AAAA');
    }
    expect(mocks.requestProjectRemoteAccess).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=projects.access.explicit-context,projects.surface.semantic-parity
  it('reads the exact root README from a connected source when no stored item exists', async () => {
    mocks.requestProjectRemoteAccess
      .mockResolvedValueOnce({ entries: [{ path: 'ReadMe.md', kind: 'file' }], omitted: 0, excluded: 0 })
      .mockResolvedValueOnce({ content: '# Remote', truncated: false, sizeBytes: 8, lineCount: 1, expectedBase: null });

    const result = await loadProjectReadme({ project, items: [], sources: [source], remoteContext: { ownerId: 'user-1', teamId: 'team-1' } });

    expect(result).toMatchObject({ status: 'ready', document: { content: '# Remote', origin: 'connected', sourceId: 'source-1' } });
    expect(mocks.requestProjectRemoteAccess).toHaveBeenNthCalledWith(
      1, project, source, { ownerId: 'user-1', teamId: 'team-1' }, 'list', { path: '.' }, undefined,
    );
    expect(mocks.requestProjectRemoteAccess).toHaveBeenNthCalledWith(
      2, project, source, { ownerId: 'user-1', teamId: 'team-1' }, 'read_text', { path: 'ReadMe.md' }, undefined,
    );
  });

  // contract-test: supporting surface=gui.web assertions=projects.access.explicit-context,projects.surface.semantic-parity
  it('shows the empty state only when a connected source was checked and has no root README', async () => {
    mocks.requestProjectRemoteAccess.mockResolvedValue({
      entries: [{ path: 'docs/README.md', kind: 'file' }], omitted: 0, excluded: 0,
    });
    const result = await loadProjectReadme({ project, items: [], sources: [source], remoteContext: { ownerId: 'user-1' } });
    expect(result.status).toBe('empty');
    expect(mocks.requestProjectRemoteAccess).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=projects.access.explicit-context,projects.surface.semantic-parity
  it('does not mistake a failed or offline source check for an absent README', async () => {
    mocks.requestProjectRemoteAccess.mockRejectedValueOnce(new Error('Source unavailable'));
    const failed = await loadProjectReadme({ project, items: [], sources: [source], remoteContext: { ownerId: 'user-1' } });
    expect(failed.status).toBe('error');

    const offline = { ...source, status: 'offline' as const };
    const unavailable = await loadProjectReadme({ project, items: [], sources: [offline], remoteContext: { ownerId: 'user-1' } });
    expect(unavailable.status).toBe('error');

    mocks.requestProjectRemoteAccess.mockResolvedValueOnce({ entries: [], omitted: 1, excluded: 0 });
    const incomplete = await loadProjectReadme({ project, items: [], sources: [source], remoteContext: { ownerId: 'user-1' } });
    expect(incomplete.status).toBe('error');
  });
});
