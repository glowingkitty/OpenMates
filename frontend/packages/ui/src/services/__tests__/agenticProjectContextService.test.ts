import { stringify as stringifyYaml } from 'yaml';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';

const mocks = vi.hoisted(() => ({ focus: vi.fn(), project: vi.fn(), contents: vi.fn(), head: vi.fn() }));
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../../stores/authStore', async () => {
  const { writable } = await import('svelte/store');
  return { authStore: writable({ isAuthenticated: true }) };
});
vi.mock('../../stores/userProfile', async () => {
  const { writable } = await import('svelte/store');
  return { userProfile: writable({ user_id: 'owner' }) };
});
vi.mock('../projectService', () => ({
  getActiveProjectFocus: mocks.focus, getProject: mocks.project,
  getProjectContents: mocks.contents, readEncryptedProjectFile: mocks.head,
}));
vi.mock('../ruleDocumentService', () => ({ readActiveProjectMarkdownDocuments: mocks.head }));
import {
  collectProjectFocusCatalog, collectPrivateFocusForRequest, loadSelectedProjectFocusDocuments, parseProjectFocusDocument,
} from '../agenticProjectContextService';

const markdown = '---\nname: Project debugging\ndescription: Investigate service failures.\npreprocessor_hint: Debugging Python services.\nphases:\n  - id: investigate\n    name: Investigate\n    instructions: Find the root cause.\n---\nKeep private debugging notes within the approved task.\n';
const item = {
  project_item_id: '11111111-1111-4111-8111-111111111111', target_id: 'embed-id', item_type: 'embed',
  metadata: { focus_title: 'Project debugging', focus_description: 'Investigate failures.', focus_when_to_use: 'Debug Python.', display_path: '.openmates/focuses/focus-1/SKILL.md' },
  encrypted: { updated_at: 1, encrypted_metadata: 'ciphertext', target_id_hash: 'opaque-target' },
};

describe('Project focus catalog boundaries', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
    vi.stubGlobal('crypto', webcrypto);
    mocks.focus.mockResolvedValue({ project_id: 'project-1', team_id: null });
    mocks.project.mockResolvedValue({ project_id: 'project-1' });
    mocks.contents.mockResolvedValue({ items: [item], folders: [] });
    mocks.head.mockResolvedValue([{ item_id: item.project_item_id, path: item.metadata.display_path, document: markdown, file_revision: 1 }]);
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click,projects.focus.default-owned
  it('returns metadata without loading private instructions, and nothing before activation', async () => {
    const catalog = await collectProjectFocusCatalog({ chatId: 'chat-1', projectId: 'project-1' });
    expect(catalog[0].id).toBe(item.project_item_id);
    expect(catalog[0].revision).toMatch(/^[a-f0-9]{64}$/);
    expect(JSON.stringify(catalog)).not.toContain('private debugging notes');
    expect(mocks.head).not.toHaveBeenCalled();
    mocks.focus.mockResolvedValue(null);
    vi.clearAllMocks();
    expect(await collectProjectFocusCatalog({ chatId: 'chat-1', projectId: 'project-1' })).toEqual([]);
    expect(mocks.project).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click
  it('selects metadata on the server before reading only authorized exact Markdown bodies', async () => {
    const catalog = await collectProjectFocusCatalog({ chatId: 'chat-1' });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ selected: [
      { kind: 'focus', id: item.project_item_id, revision: catalog[0].revision },
      { kind: 'focus', id: 'invented', revision: 'a'.repeat(64) },
    ] }));
    const documents = await collectPrivateFocusForRequest({ chatId: 'chat-1', text: 'Debug the failure' });
    expect(documents).toEqual([{ item_id: item.project_item_id, revision: catalog[0].revision, document: markdown }]);
    const body = String(fetchMock.mock.calls[0][1]?.body);
    expect(body).toContain('Project debugging');
    expect(body).not.toContain('private debugging notes');
    expect(mocks.head).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click,projects.focus.default-owned
  it('retains the canonical active specialist when optional metadata selection fails', async () => {
    mocks.focus.mockResolvedValue({ project_id: 'project-1', team_id: null,
      specialist_focus_id: `project-focus:project-1:${item.project_item_id}` });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 503 }));
    const documents = await collectPrivateFocusForRequest({ chatId: 'chat-1', text: 'Continue the task' });
    expect(documents).toEqual([{ item_id: item.project_item_id,
      revision: (await collectProjectFocusCatalog({ chatId: 'chat-1' }))[0].revision, document: markdown }]);
    expect(mocks.head).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click
  it('rejects incomplete recommendation catalogs rather than implying no existing Focus overlaps', async () => {
    mocks.contents.mockResolvedValue({ items: Array.from({ length: 41 }, (_, index) => ({ ...item, project_item_id: `focus-${index}` })), folders: [] });
    await expect(collectProjectFocusCatalog({ chatId: 'chat-1' })).rejects.toThrow('focus_catalog_limit');
    expect(mocks.head).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click,projects.focus.default-owned
  it('drops selected bodies if Project activation or metadata revision changes during loading', async () => {
    mocks.head.mockImplementation(async () => {
      mocks.focus.mockResolvedValue(null);
      return [{ item_id: item.project_item_id, path: item.metadata.display_path, document: markdown, file_revision: 1 }];
    });
    expect(await loadSelectedProjectFocusDocuments('chat-1', 'project-1', [item.project_item_id])).toEqual([]);
    mocks.focus.mockResolvedValue({ project_id: 'project-1', team_id: null });
    mocks.head.mockImplementation(async () => {
      mocks.contents.mockResolvedValue({ items: [{ ...item, encrypted: { ...item.encrypted, updated_at: 2 } }], folders: [] });
      return [{ item_id: item.project_item_id, path: item.metadata.display_path, document: markdown, file_revision: 1 }];
    });
    expect(await loadSelectedProjectFocusDocuments('chat-1', 'project-1', [item.project_item_id])).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-persistence
  it('validates complete saved Focus metadata and ordered phases without accepting aliases', () => {
    expect(parseProjectFocusDocument(markdown).phases).toEqual([{ id: 'investigate', name: 'Investigate', instructions: 'Find the root cause.' }]);
    expect(() => parseProjectFocusDocument(markdown.replace('description: Investigate service failures.', 'description: &x Investigate\nunknown: *x'))).toThrow();
    expect(() => parseProjectFocusDocument(markdown.replace('name: Project debugging', 'name: ""'))).toThrow();
  });

const phaseMetadata = { name: 'Debugging', description: 'Synthetic source checks', when_to_use: 'Synthetic incidents' };
const canonicalPhases = [{ id: 'inspect', title: 'Inspect', instructions: 'Compare source.', requirements: [
  { id: 'matched', text: 'Source matches.', type: 'semantic' },
  { id: 'approved', text: 'The user confirms.', type: 'user_confirmation' },
] }, { id: 'diagnose', title: 'Diagnose', instructions: 'Read bounded logs.', requirements: [{ id: 'diagnosed', text: 'Evidence explains the failure.' }] }];
const canonicalMarkdown = (fields: Record<string, unknown>) => `---\n${stringifyYaml({ ...phaseMetadata, ...fields })}---\nKeep global guidance.`;

// contract-test: supporting surface=gui.web assertions=focus-modes.phases,focus-modes.project-authoring-persistence
it('preserves complete versioned phase definitions and ordered requirements in the selected private document', async () => {
  const source = canonicalMarkdown({ phases_version: 1, phases: canonicalPhases });
  expect(parseProjectFocusDocument(source)).toEqual({ ...phaseMetadata, phases_version: 1, phases: canonicalPhases, instructions: 'Keep global guidance.' });
  mocks.focus.mockResolvedValue({ project_id: 'project-1', team_id: null });
  mocks.project.mockResolvedValue({ project_id: 'project-1' });
  mocks.contents.mockResolvedValue({ items: [item], folders: [] });
  mocks.head.mockResolvedValue([{ item_id: item.project_item_id, path: item.metadata.display_path, document: source, file_revision: 1 }]);
  const selected = await loadSelectedProjectFocusDocuments('chat-1', 'project-1', [item.project_item_id]);
  expect(selected[0].document.phases).toEqual(canonicalPhases);
  expect(selected[0].document.phases_version).toBe(1);
});

// contract-test: supporting surface=gui.web assertions=focus-modes.phases,focus-modes.project-authoring-persistence
it('rejects unsupported or incomplete canonical phases instead of silently converting them to legacy', () => {
  const invalid = [
    ...[true, false, 2, null].map(phases_version => ({ phases_version, phases: canonicalPhases })),
    { phases_version: 1, phases: [] }, { phases: canonicalPhases },
    { phases_version: 1, phases: [{ id: 'legacy', name: 'Legacy', instructions: 'PRIVATE-PHASE-SENTINEL' }] },
    { phases_version: 1, phases: [canonicalPhases[0], canonicalPhases[0]] },
    { phases_version: 1, phases: [{ ...canonicalPhases[0], requirements: [] }] },
    { phases_version: 1, phases: [{ ...canonicalPhases[0], requirements: [canonicalPhases[0].requirements[0], canonicalPhases[0].requirements[0]] }] },
    { phases_version: 1, phases: [{ ...canonicalPhases[0], requirements: [{ id: 'gate', text: 'PRIVATE-PHASE-SENTINEL', type: 'permission' }] }] },
  ];
  for (const metadata of invalid) expect(() => parseProjectFocusDocument(canonicalMarkdown(metadata))).toThrow('invalid_focus_document');
  const legacy = parseProjectFocusDocument(markdown);
  expect(Object.hasOwn(legacy, 'phases_version')).toBe(false);
  expect(legacy.phases).toEqual([{ id: 'investigate', name: 'Investigate', instructions: 'Find the root cause.' }]);
});

});
