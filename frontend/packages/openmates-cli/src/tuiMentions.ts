/** Typing-time mention picker. Private catalogs use the existing encrypted owner/Team cache. */
import { MATE_NAMES, type OpenMatesClient } from './client.js';
import type { MentionContext } from './mentions.js';
import type { TuiState } from './tuiRenderer.js';
import type { TerminalKey } from './tuiTerminal.js';
import { isTuiAiComposer, type TuiModelSelectorShell } from './tuiModelSelectorShell.js';
import { captureTuiWorkspaceOwner, loadCachedTuiWorkspace, readCachedTuiWorkspace } from './tuiCachedWorkspaces.js';
import { loadTuiApps } from './tuiAppsWorkspace.js';
import { loadTuiProjects, type TuiProject } from './tuiProjectsWorkspace.js';
import { buildTuiMentionCatalog, extractTuiMention, searchTuiMentionCatalog, type TuiMentionProject, type TuiMentionSuggestion } from './tuiMentionCatalog.js';
import { terminalText, type TuiLine } from './tuiText.js';
import type { TuiModelEntry } from './tuiModelSelector.js';

export interface TuiMentionData { context: MentionContext; projects: TuiMentionProject[]; incomplete?: boolean }
export interface TuiMentionPicker {
  generation: number; input: string; cursor: number; start: number; end: number; query: string;
  items: TuiMentionSuggestion[]; selectedIndex: number; loading: boolean; busy: boolean; error: string | null;
}
const emptyData = (): TuiMentionData => ({ context: { models: [], mates: MATE_NAMES, apps: [], memoryEntries: [] }, projects: [] });

async function fetchMentionData(client: OpenMatesClient, previous: TuiMentionData): Promise<TuiMentionData> {
  const current = captureTuiWorkspaceOwner(client);
  const [appsResult, memoriesResult, projectsResult] = await Promise.allSettled([
    loadTuiApps(client), client.listMemories(),
    readCachedTuiWorkspace<TuiProject[]>(client, 'projects:list').then(value => value ?? loadTuiProjects(client)),
  ]);
  if (!current()) throw new Error('Mention context changed.');
  if ([appsResult, memoriesResult, projectsResult].every(result => result.status === 'rejected')) throw new Error('Mention sources are unavailable.');
  const projects = projectsResult.status === 'fulfilled' ? projectsResult.value : [];
  const choices: TuiMentionProject[] = projectsResult.status === 'fulfilled' ? [] : previous.projects;
  // Read only already-known metadata. Never enumerate remote files while typing.
  for (let offset = 0; offset < projects.length; offset += 4) {
    if (!current()) throw new Error('Mention context changed.');
    choices.push(...await Promise.all(projects.slice(offset, offset + 4).filter(project => !project.archived).map(async project => {
      const detail = await readCachedTuiWorkspace<TuiProject>(client, `project:${project.id}:detail`);
      const files = detail?.files ?? project.files;
      return { id: project.id, name: project.name, description: project.description, accessMode: 'read' as const,
        files: files.filter(file => file.kind !== 'folder').map(file => ({ path: file.path, name: file.name, sourceId: file.sourceId })),
        folders: files.filter(file => file.kind === 'folder').map(file => ({ path: file.path, name: file.name, sourceId: file.sourceId })),
      };
    })));
  }
  if (!current()) throw new Error('Mention context changed.');
  return { context: { models: [], mates: MATE_NAMES,
    apps: appsResult.status === 'fulfilled' ? appsResult.value.map(app => ({ id: app.id, name: app.name, skills: app.skills,
      focus_modes: app.focusModes, settings_and_memories: app.settingsMemories })) : previous.context.apps,
    memoryEntries: memoriesResult.status === 'fulfilled' ? memoriesResult.value.sort((a,b)=>b.updated_at-a.updated_at).map(entry => ({ id: entry.id, app_id: entry.app_id, item_type: entry.item_type,
      title: [entry.data?.title, entry.data?.name, entry.data?.label, entry.data?._original_item_key].find(value => typeof value === 'string' && value.trim()) as string | undefined })) : previous.context.memoryEntries,
  }, projects: choices, incomplete: [appsResult, memoriesResult, projectsResult].some(result => result.status === 'rejected') };
}

export function renderTuiMentions(picker: TuiMentionPicker): TuiLine[] {
  const types: Record<string, string> = { model: 'Model', model_alias: 'Model shortcut', mate: 'Mate', skill: 'App skill',
    focus_mode: 'Focus mode', settings_memory: 'Memories', settings_memory_entry: 'Saved memory',
    project: 'Project', project_folder: 'Folder', project_file: 'File', wikipedia_source: 'Source', wikipedia: 'Wikipedia', team_ai: 'Team AI' };
  return [{ text: '@ Suggestions', bold: true, color: '#80caff' },
    ...picker.items.map((item, index): TuiLine => ({ text: `${index === picker.selectedIndex ? '›' : ' '} ${item.label} · ${types[item.type] ?? item.type} · ${item.description}`,
      color: index === picker.selectedIndex ? '#32ade6' : '#d7e3ef', bold: index === picker.selectedIndex,
      action: { kind: 'command', command: `/mention-select ${picker.generation}:${index}` } })),
    ...(!picker.items.length ? [{ text: picker.loading ? 'Loading suggestions…' : picker.error ?? 'No matching suggestions', color: '#a0a0a0' }] : []),
    { text: picker.busy ? 'Choosing…' : '↑/↓ choose · Enter/Tab insert · Esc close', color: '#a0a0a0' }];
}

export function createTuiMentionShell(args: { state: TuiState; client: OpenMatesClient; modelShell: TuiModelSelectorShell;
  render: () => void; fetchData?: () => Promise<TuiMentionData> }) {
  const { state, client, modelShell, render } = args;
  let data = emptyData(), loaded = false, loading = false, disposed = false, epoch = 0, generation = 0;
  let refreshAfter = 0, projectRevision = state.projects, memoryRevision = state.continueData, settingsOpen = Boolean(state.settings);
  let owner: (() => boolean) | null = null, dismissed: string | null = null, lastSearch = '', catalog: TuiMentionSuggestion[] = [];
  let models: TuiModelEntry[] | null | undefined;
  let wikiTimer: ReturnType<typeof setTimeout> | null = null;
  const stopWiki = () => { if (wikiTimer) clearTimeout(wikiTimer); wikiTimer = null; };
  const clear = () => { stopWiki(); state.mentionPicker = null; lastSearch = ''; };
  const eligible = () => !disposed && state.signedIn && client.hasSession() && state.focus === 'composer' && isTuiAiComposer(state)
    && !state.input.startsWith('/') && !state.form && !state.settings && !state.chrome && !state.paletteOpen && !state.questionEditor
    && !state.modelSelector?.open && !state.textSelection && !state.startup && !state.privacyOffer;
  const load = () => {
    if (loading || loaded && Date.now() < refreshAfter) return;
    loading = true;
    const request = epoch, fence = owner!;
    void loadCachedTuiWorkspace(client, 'mentions:catalog:v1', args.fetchData ?? (() => fetchMentionData(client,data)), next => {
      if (disposed || epoch !== request || !fence()) return;
      data = next; loaded = true; catalog = []; lastSearch = ''; render();
      refreshAfter = Date.now() + (next.incomplete ? 60_000 : 300_000);
    }, () => { if (epoch === request && fence() && state.mentionPicker) state.mentionPicker.error = 'More suggestions are unavailable offline.'; })
      .finally(() => { if (epoch === request && fence()) { loading = false; loaded = true; refreshAfter = Math.max(refreshAfter, Date.now()+60_000); lastSearch = ''; render(); } });
  };
  const sync = () => {
    if (owner && !owner()) { epoch++; owner = null; data = emptyData(); loaded = false; loading = false; catalog = []; models = null; dismissed = null; clear(); }
    if (projectRevision !== state.projects || memoryRevision !== state.continueData || settingsOpen && !state.settings) refreshAfter = 0;
    projectRevision = state.projects; memoryRevision = state.continueData; settingsOpen = Boolean(state.settings);
    if (!eligible()) { clear(); return; }
    if (!owner) owner = captureTuiWorkspaceOwner(client);
    if (!owner()) { clear(); return; }
    const cursor = state.inputCursor ?? state.input.length, range = extractTuiMention(state.input, cursor);
    const signature = JSON.stringify([state.routeVersion, state.input, cursor]);
    if (!range || signature === dismissed) { clear(); return; }
    load();
    if (models !== state.modelSelector?.models || !catalog.length) {
      models = state.modelSelector?.models;
      catalog = buildTuiMentionCatalog(data.context, state.modelSelector?.models ?? [], data.projects, Boolean(state.activeTeamId));
      lastSearch = '';
    }
    if (lastSearch === signature) return;
    lastSearch = signature; stopWiki();
    const old = state.mentionPicker, selectedId = old?.query === range.query ? old.items[old.selectedIndex]?.id : null;
    const picker: TuiMentionPicker = { ...range, generation: ++generation, input: state.input, cursor,
      items: searchTuiMentionCatalog(catalog, range.query), selectedIndex: 0, loading, busy: false, error: old?.error ?? null };
    const selected = picker.items.findIndex(item => item.id === selectedId); if (selected >= 0) picker.selectedIndex = selected;
    state.mentionPicker = picker;
    if (range.query.toLowerCase().startsWith('wiki:')) {
      picker.items = []; picker.loading = true;
      const raw = range.query.slice(5), languagePrefix = raw.match(/^([a-z]{2,3}(?:-[a-z0-9]{2,8})?):/i);
      const language = languagePrefix?.[1].toLowerCase() ?? 'en';
      const query = raw.slice(languagePrefix?.[0].length ?? 0).replace(/_/g, ' '), request = epoch, route = state.routeVersion, fence = owner;
      if (!query) { picker.loading = false; picker.error = 'Type an article name after @wiki:'; return; }
      wikiTimer = setTimeout(() => {
        wikiTimer = null;
        void client.searchWikipediaTitles(query, language, 5).then(results => {
          if (disposed || epoch !== request || !fence() || state.routeVersion !== route || state.mentionPicker !== picker || !eligible()) return;
          picker.items = results.filter(item => !item.disambiguation).map(item => ({ id: `wiki:${item.language}:${item.key}`,
            type: 'wikipedia', label: `@${terminalText(item.title)}`, description: terminalText(item.description ?? 'Wikipedia article'),
            wireSyntax: `@wikipedia:${item.language}:${encodeURIComponent(item.key)}` }));
          picker.loading = false; render();
        }).catch(() => {
          if (epoch === request && fence() && state.mentionPicker === picker) { picker.loading = false; picker.error = 'Wikipedia search unavailable. Your draft is kept.'; render(); }
        });
      }, 200);
    }
  };
  const close = () => { dismissed = JSON.stringify([state.routeVersion, state.input, state.inputCursor ?? state.input.length]); clear(); render(); };
  const select = async (token: string) => {
    sync(); const picker = state.mentionPicker;
    if (!picker || picker.busy || !eligible() || !owner?.()) return;
    const [version, index] = token.split(':').map(Number), item = picker.items[index];
    if (version !== picker.generation || !Number.isInteger(index) || !item) return;
    const route = state.routeVersion, fence = owner;
    const current = () => !disposed && fence() && state.routeVersion === route && state.mentionPicker === picker
      && state.input === picker.input && (state.inputCursor ?? state.input.length) === picker.cursor;
    let wire = item.wireSyntax;
    if (item.type.startsWith('project') && typeof client.getProjectSettings === 'function') {
      // Resolve just the chosen Project's write mode; @ must not fetch all settings.
      picker.busy = true; render();
      const settings = await client.getProjectSettings(wire.split(':')[1]).catch(() => null);
      if (!current()) return;
      wire = wire.replace(/:(?:read|read_write)$/, settings?.write_mode === 'apply_and_show' ? ':read_write' : ':read');
      picker.busy = false;
    }
    const suffix = item.type === 'wikipedia_source' ? '' : ' ';
    let value = picker.input.slice(0, picker.start) + wire + suffix + picker.input.slice(picker.end);
    let cursor = picker.start + wire.length + suffix.length;
    if (item.type === 'wikipedia' && (picker.input.match(/@(?:wikipedia:|wiki:)/g)?.length ?? 0) > 3) {
      picker.error = 'Use at most 3 Wikipedia references per message.'; render(); return;
    }
    if (item.modelId) {
      picker.busy = true; render();
      const result = await modelShell.consumeMention(value, true);
      if (!fence() || state.routeVersion !== route || state.mentionPicker !== picker || state.input !== picker.input || (state.inputCursor ?? state.input.length) !== picker.cursor) return;
      if (result.blocked) { picker.busy = false; render(); return; }
      cursor = Math.max(picker.start, cursor - (value.length - result.message.length)); value = result.message;
    }
    if (!fence() || state.routeVersion !== route || state.input !== picker.input || (state.inputCursor ?? state.input.length) !== picker.cursor) return;
    state.input = value; state.inputCursor = cursor; state.drafts[state.activeChatId ?? 'new'] = value;
    dismissed = null; clear(); render();
  };
  const key = async (_chunk: string, key: TerminalKey): Promise<boolean> => {
    sync(); const picker = state.mentionPicker;
    if (!picker) return false;
    if (key.name === 'escape') { close(); return true; }
    if (key.ctrl || key.meta || key.shift && key.name === 'tab') return false;
    if (key.name === 'up' || key.name === 'down') {
      if (picker.items.length) picker.selectedIndex = (picker.selectedIndex + (key.name === 'up' ? -1 : 1) + picker.items.length) % picker.items.length;
      render(); return true;
    }
    if (key.name === 'return' || key.name === 'tab') {
      if (picker.items.length) await select(`${picker.generation}:${picker.selectedIndex}`);
      return true; // Selection never sends a message, including loading/empty states.
    }
    return false;
  };
  return { sync, key, select, close, refresh: () => { refreshAfter = 0; }, dispose: () => { disposed = true; epoch++; clear(); data = emptyData(); catalog = []; } };
}
export type TuiMentionShell = ReturnType<typeof createTuiMentionShell>;
