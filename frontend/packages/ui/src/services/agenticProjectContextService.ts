/** Fresh active-Project catalogs; private bodies are resolved only for selected IDs. */
import { get } from 'svelte/store';
import { parseDocument, isAlias, visit } from 'yaml';
import { projectFocusDocumentFromMetadata, type ProjectFocusDocument } from '../../../projectFocusDocument';
export type { ProjectFocusDocument } from '../../../projectFocusDocument';
import { authStore } from '../stores/authStore';
import { userProfile } from '../stores/userProfile';
import { projectRecordRevision } from '../utils/projectContextRevision';
import { getApiEndpoint } from '../config/api';
import {
  getActiveProjectFocus, getProject, getProjectContents,
  type ProjectItemViewModel,
} from './projectService';
import { readActiveProjectMarkdownDocuments } from './ruleDocumentService';

export interface ProjectFocusCatalogEntry {
  kind: 'focus';
  id: string;
  title: string;
  summary: string;
  when_to_use: string;
  revision: string;
  display_path: string;
}


export async function projectItemRevision(item: ProjectItemViewModel): Promise<string> {
  return projectRecordRevision(item.encrypted as unknown as Record<string, unknown>);
}

async function activeWorkspace(chatId: string, projectId?: string | null) {
  const owner = get(userProfile).user_id;
  if (!get(authStore).isAuthenticated || !owner) return null;
  const focus = await getActiveProjectFocus(chatId);
  if (!focus || projectId && focus.project_id !== projectId) return null;
  const context = { teamId: focus.team_id };
  const project = await getProject(focus.project_id, context);
  const contents = await getProjectContents(project, context);
  const fresh = await getActiveProjectFocus(chatId);
  if (!get(authStore).isAuthenticated || get(userProfile).user_id !== owner
    || fresh?.project_id !== focus.project_id || fresh?.team_id !== focus.team_id) return null;
  return { owner, focus, project, contents, context };
}

function focusItem(item: ProjectItemViewModel): boolean {
  return !!item.target_id && ['embed', 'upload'].includes(item.item_type)
    && typeof item.metadata.focus_title === 'string'
    && typeof item.metadata.focus_description === 'string'
    && typeof item.metadata.focus_when_to_use === 'string'
    && typeof item.metadata.display_path === 'string'
    && /^\.openmates\/focuses\/[a-zA-Z0-9_-]+\/SKILL\.md$/.test(item.metadata.display_path);
}

function specialistItemId(projectId: string, focusId?: string | null): string | undefined {
  const prefix = `project-focus:${projectId}:`;
  return focusId?.startsWith(prefix) ? focusId.slice(prefix.length) : focusId ?? undefined;
}

export async function collectProjectFocusCatalog(input: { chatId: string; projectId?: string | null }): Promise<ProjectFocusCatalogEntry[]> {
  const workspace = await activeWorkspace(input.chatId, input.projectId);
  if (!workspace) return [];
  const specialistId = specialistItemId(workspace.focus.project_id, workspace.focus.specialist_focus_id);
  const ordered = workspace.contents.items.filter(focusItem).sort((a, b) =>
    Number(b.project_item_id === specialistId) - Number(a.project_item_id === specialistId));
  if (ordered.length > 40) throw new Error('focus_catalog_limit');
  const result = await Promise.all(ordered.map(async (item) => ({
    kind: 'focus' as const, id: item.project_item_id,
    title: String(item.metadata.focus_title).slice(0, 180),
    summary: String(item.metadata.focus_description).slice(0, 1_200),
    when_to_use: String(item.metadata.focus_when_to_use).slice(0, 1_200),
    revision: await projectItemRevision(item), display_path: String(item.metadata.display_path),
  })));
  return get(authStore).isAuthenticated && get(userProfile).user_id === workspace.owner ? result : [];
}

export function parseProjectFocusDocument(markdown: string): ProjectFocusDocument {
  if (markdown.length > 96_000) throw new Error('focus_document_limit');
  const match = markdown.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)([\s\S]*)$/);
  if (!match) throw new Error('invalid_focus_document');
  try {
    const parsed = parseDocument(match[1], { uniqueKeys: true, schema: 'core' });
    if (parsed.errors.length) throw new Error('invalid_focus_document');
    visit(parsed, (_key, node) => { if (isAlias(node)) throw new Error('invalid_focus_document'); });
    return projectFocusDocumentFromMetadata(parsed.toJS({ maxAliasCount: 0 }), match[2]);
  } catch { throw new Error('invalid_focus_document'); }
}

export async function loadSelectedProjectFocusDocuments(
  chatId: string, projectId: string, itemIDs: readonly string[],
): Promise<Array<{ id: string; revision: string; document: ProjectFocusDocument; markdown: string }>> {
  if (!itemIDs.length) return [];
  if (itemIDs.length > 6 || new Set(itemIDs).size !== itemIDs.length) throw new Error('focus_selection_limit');
  const workspace = await activeWorkspace(chatId, projectId);
  if (!workspace) return [];
  const result = [];
  let total = 0;
  const selectedItems = workspace.contents.items.filter((candidate) => itemIDs.includes(candidate.project_item_id) && focusItem(candidate));
  const files = await readActiveProjectMarkdownDocuments({ chatId, projectId,
    requests: selectedItems.map((item) => ({ itemId: item.project_item_id, path: String(item.metadata.display_path) })),
  });
  for (const file of files) {
    const item = selectedItems.find((candidate) => candidate.project_item_id === file.item_id)!;
    if (!get(authStore).isAuthenticated || get(userProfile).user_id !== workspace.owner) return [];
    const markdown = file.document;
    total += markdown.length;
    if (total > 60_000) throw new Error('focus_selection_limit');
    result.push({ id: item.project_item_id, revision: await projectItemRevision(item), document: parseProjectFocusDocument(markdown), markdown });
  }
  const fresh = await activeWorkspace(chatId, projectId);
  if (!fresh || fresh.owner !== workspace.owner) return [];
  const retained = [];
  for (const entry of result) {
    const current = fresh.contents.items.find((item) => item.project_item_id === entry.id);
    if (current && await projectItemRevision(current) === entry.revision) retained.push(entry);
  }
  return get(authStore).isAuthenticated && get(userProfile).user_id === workspace.owner ? retained : [];
}

export async function collectPrivateFocusForRequest(input: {
  chatId: string; projectId?: string | null; text: string;
}): Promise<Array<{ item_id: string; revision: string; document: string }>> {
  const catalog = await collectProjectFocusCatalog(input);
  if (!catalog.length) return [];
  const focus = await getActiveProjectFocus(input.chatId);
  if (!focus || input.projectId && focus.project_id !== input.projectId) return [];
  const response = await fetch(getApiEndpoint(`/v1/projects/${encodeURIComponent(focus.project_id)}/context/select${focus.team_id ? `?team_id=${encodeURIComponent(focus.team_id)}` : ''}`), {
    method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: input.chatId, text: input.text.slice(0, 8_000), candidates: catalog.slice(0, 24).map((item) => ({
      kind: item.kind, id: item.id, title: item.title, description: item.summary.slice(0, 640),
      when_to_use: item.when_to_use.slice(0, 640), revision: item.revision,
    })) }),
  });
  const result: unknown = response.ok ? await response.json() : null;
  const offered = result && typeof result === 'object' && Array.isArray((result as Record<string, unknown>).selected)
    ? (result as Record<string, unknown>).selected as Array<Record<string, unknown>> : [];
  const selected = offered
    .filter((item) => item.kind === 'focus' && typeof item.id === 'string' && typeof item.revision === 'string'
      && catalog.some((candidate) => candidate.id === item.id && candidate.revision === item.revision)).slice(0, 4);
  const activeSpecialist = catalog.find((item) => item.id === specialistItemId(focus.project_id, focus.specialist_focus_id));
  if (activeSpecialist && !selected.some((item) => item.id === activeSpecialist.id)) {
    selected.push({ kind: 'focus', id: activeSpecialist.id, revision: activeSpecialist.revision });
  }
  const documents = await loadSelectedProjectFocusDocuments(input.chatId, focus.project_id, selected.map((item) => String(item.id)));
  return documents.filter((item) => selected.some((candidate) => candidate.id === item.id && candidate.revision === item.revision))
    .map((item) => ({ item_id: item.id, revision: item.revision, document: item.markdown }));
}

export interface ProjectReferenceDocument {
  item_id: string;
  kind: 'spec' | 'memory' | 'fact' | 'folder';
  title: string;
  description: string;
  document: string;
  revision: string;
}

export async function collectProjectReferenceDocuments(input: {
  chatId: string; projectId?: string | null; text: string;
}): Promise<ProjectReferenceDocument[]> {
  const workspace = await activeWorkspace(input.chatId, input.projectId);
  if (!workspace) return [];
  const catalog: Array<{ kind: ProjectReferenceDocument['kind']; id: string; title: string; description: string; revision: string; path?: string; document?: string }> = [];
  for (const item of workspace.contents.items) {
    const path = item.metadata.path ?? item.metadata.display_path;
    if (typeof path !== 'string' || !/^\.openmates\/(specs|memories|facts)\/[^\0]+\.md$/.test(path)
      || path.split('/').some((part) => !part || part === '..' || part === '.')) continue;
    catalog.push({ kind: path.startsWith('.openmates/specs/') ? 'spec' : 'memory', id: item.project_item_id,
      title: String(item.metadata.title ?? item.displayName ?? path).slice(0, 200),
      description: String(item.metadata.description ?? item.metadata.summary ?? '').slice(0, 640),
      revision: await projectItemRevision(item), path });
    if (catalog.length >= 20) break;
  }
  for (const folder of workspace.contents.folders.slice(0, 24 - catalog.length)) {
    catalog.push({ kind: 'folder', id: folder.folder_id, title: folder.name.slice(0, 200), description: '',
      revision: await projectRecordRevision(folder.encrypted as unknown as Record<string, unknown>),
      document: JSON.stringify({ name: folder.name, parent_reference: folder.parentHash }) });
  }
  if (!catalog.length || !get(authStore).isAuthenticated || get(userProfile).user_id !== workspace.owner) return [];
  const response = await fetch(getApiEndpoint(`/v1/projects/${encodeURIComponent(workspace.project.project_id)}/context/select${workspace.focus.team_id ? `?team_id=${encodeURIComponent(workspace.focus.team_id)}` : ''}`), {
    method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: input.chatId, text: input.text.slice(0, 8_000), candidates: catalog.map(({ kind, id, title, description, revision }) => ({ kind, id, title, description, revision })) }),
  });
  if (!response.ok) return [];
  const value: unknown = await response.json();
  if (!value || typeof value !== 'object' || !Array.isArray((value as Record<string, unknown>).selected)) return [];
  const selected = ((value as Record<string, unknown>).selected as Array<Record<string, unknown>>).slice(0, 4)
    .flatMap((entry) => {
      const candidate = catalog.find((item) => item.id === entry.id && item.kind === entry.kind && item.revision === entry.revision);
      return candidate ? [candidate] : [];
    });
  const files = selected.some((item) => item.path) ? await readActiveProjectMarkdownDocuments({
    chatId: input.chatId, projectId: workspace.project.project_id,
    requests: selected.filter((item) => item.path).map((item) => ({ itemId: item.id, path: item.path! })),
  }) : [];
  const fresh = await activeWorkspace(input.chatId, workspace.project.project_id);
  if (!fresh || fresh.owner !== workspace.owner) return [];
  const result: ProjectReferenceDocument[] = [];
  for (const entry of selected) {
    const source = entry.kind === 'folder'
      ? fresh.contents.folders.find((item) => item.folder_id === entry.id)?.encrypted
      : fresh.contents.items.find((item) => item.project_item_id === entry.id)?.encrypted;
    if (!source || await projectRecordRevision(source as unknown as Record<string, unknown>) !== entry.revision) continue;
    const document = entry.document ?? files.find((file) => file.item_id === entry.id)?.document;
    if (document) result.push({ item_id: entry.id, kind: entry.kind, title: entry.title,
      description: entry.description, document, revision: entry.revision });
  }
  return get(authStore).isAuthenticated && get(userProfile).user_id === workspace.owner ? result : [];
}
