<!--
  ProjectsPage.svelte
  Projects V1 workspace UI for manually organizing chats, embeds, and uploads.
  Files uploaded here are converted into embeds first and then linked through
  project_items, so project storage follows the same encryption/rendering model
  as the rest of OpenMates.
-->

<script lang="ts">
  import { onMount, setContext, tick } from 'svelte';
  import { pushState, replaceState } from '$app/navigation';
  import { text } from '@repo/ui';
  import { SettingsTabs } from '../settings/elements';
  import UnifiedEmbedPreview from '../embeds/UnifiedEmbedPreview.svelte';
  import CodeEmbedFullscreen from '../embeds/code/CodeEmbedFullscreen.svelte';
  import FileEmbedFullscreen from '../embeds/file/FileEmbedFullscreen.svelte';
  import ImageEmbedFullscreen from '../embeds/images/ImageEmbedFullscreen.svelte';
  import ProjectBrowserItem from './ProjectBrowserItem.svelte';
  import ProjectReadme from './ProjectReadme.svelte';
  import ProjectWorkspaceHeader from './ProjectWorkspaceHeader.svelte';
  import ProjectRemotePreviewCard from './ProjectRemotePreviewCard.svelte';
  import TasksPage from '../tasks/TasksPage.svelte';
  import type { TasksBoardItem } from '../../services/userTaskService';
  import WorkspaceHomeShell from '../workspace/WorkspaceHomeShell.svelte';
  import WorkspacePromptComposer from '../workspace/WorkspacePromptComposer.svelte';
  import { notificationStore } from '../../stores/notificationStore';
  import { authStore } from '../../stores/authStore';
  import { panelState } from '../../stores/panelStateStore';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { userProfile } from '../../stores/userProfile';
  import { getActiveTeamContextSnapshot } from '../../stores/teamStore';
  import { computeSHA256 } from '../../message_parsing/utils';
  import { normalizeEmbedType as registryNormalizeEmbedType } from '../../data/embedRegistry.generated';
  import { hasFullscreenComponent, loadFullscreenComponent, resolveRegistryKey } from '../../services/embedFullscreenResolver';
  import type { EmbedFullscreenDispatchDetail } from '../../services/embedFullscreenController';
  import { EMBED_CHAT_CONTEXT, type EmbedChatContext } from '../../types/embedFullscreen';
  import {
    createProject,
    deleteProject,
    getProject,
    getProjectContents,
    listProjectSources,
    ProjectRemoteAccessError,
    readEncryptedProjectFile,
    listProjects,
    requestProjectRemoteAccess,
    updateProjectMetadata,
    uploadFileToProject,
    type ProjectFolderViewModel,
    type ProjectItemViewModel,
    type ProjectSourceViewModel,
    type ProjectViewModel,
    type ProjectRemoteDirectoryEntry,
    type ProjectRemoteDirectoryResult,
    type ProjectRemoteSearchResult,
    type ProjectRemoteTextResult,
  } from '../../services/projectService';
  import {
    buildRemoteFileUploadCandidate,
    buildVirtualRemoteFullscreenDetail,
    classifyRemotePreviewPath,
    normalizeRemoteFilePreview,
    type VirtualRemoteFullscreenDetail,
    type VirtualRemoteFilePreview,
    type ProjectWriteMode,
  } from '../../services/projectRemoteSources';
  import { broadcastProjectFilesChanged, PROJECTS_CHANGED_EVENT } from '../../services/projectBrowserEvents';
  import {
    projectBrowserItemName,
    projectVirtualBreadcrumbs,
    projectVirtualBrowserView,
    type ProjectVirtualFolder,
  } from '../../services/projectBrowserTree';
  import { loadProjectReadme, readConnectedProjectImage, releaseProjectReadmeImages, type ProjectReadmeState } from '../../services/projectReadme';
  import { cleanupStaleConnectedProjectDownloads, downloadConnectedProjectFile } from '../../services/projectRemoteDownload';

  type ProjectTab = 'overview' | 'folders' | 'tasks';
  // Keep expensive embed previews bounded even when a folder contains thousands of files.
  const FILES_PAGE_SIZE = 48;

  export interface ProjectCreationTarget {
    projectId: string;
    projectName: string;
    folderId?: string | null;
    folderPath?: string | null;
    sourceId?: string | null;
    teamId?: string | null;
  }

  interface PreviewState {
    project: ProjectViewModel;
    startAtHome?: boolean;
    folders?: ProjectFolderViewModel[];
    items?: ProjectItemViewModel[];
    sources?: ProjectSourceViewModel[];
    readme?: ProjectReadmeState;
    tasks?: TasksBoardItem[];
    embeds?: Record<string, {
      embedData: Record<string, unknown>;
      decodedContent: Record<string, unknown>;
    }>;
    folderCardContents?: Record<string, Array<{ name: string; kind: 'folder' | 'file'; detail?: string }>>;
    remoteEntries?: ProjectRemoteDirectoryEntry[];
    legacyRemoteEntries?: ProjectRemoteDirectoryEntry[];
  }

  interface Props {
    variant?: 'main' | 'sidebar';
    onNewChat: (target: ProjectCreationTarget) => void;
    onNewPlan: (target: ProjectCreationTarget) => void;
    onNewWorkflow: (target: ProjectCreationTarget) => void;
    previewState?: PreviewState | null;
    initialTab?: ProjectTab;
  }

  interface RemotePreviewEntry {
    preview: VirtualRemoteFilePreview;
    readResult: ProjectRemoteTextResult | null;
    canImport: boolean;
    sourceLabel: string;
  }

  type ProjectFileSearchEntry =
    | { kind: 'remote'; sourceId: string; path: string; entryKind: 'file' | 'directory' }
    | { kind: 'item'; item: ProjectItemViewModel }
    | { kind: 'folder'; folder: ProjectFolderViewModel }
    | { kind: 'virtual-folder'; folder: ProjectVirtualFolder };

  interface ProjectContinueItem {
    id: string;
    title: string;
    summary?: string | null;
    badge?: string | null;
    category?: string | null;
    appId?: string | null;
    icon?: string | null;
    source?: 'recent' | 'example';
  }

  interface ProjectInspiration {
    phrase: string;
    title?: string;
  }

  const PROJECTS_ROUTE = '/';
  const PROJECT_ID_HASH_PARAM = 'project-id';

  let { variant = 'main', onNewChat, onNewPlan, onNewWorkflow, previewState = null, initialTab = 'overview' }: Props = $props();

  let projects = $state<ProjectViewModel[]>([]);
  let selectedProject = $state<ProjectViewModel | null>(null);
  let folders = $state<ProjectFolderViewModel[]>([]);
  let items = $state<ProjectItemViewModel[]>([]);
  let sources = $state<ProjectSourceViewModel[]>([]);
  let isLoading = $state(true);
  let isSaving = $state(false);
  let newProjectName = $state('');
  let newProjectWriteMode = $state<ProjectWriteMode | null>(null);
  let pendingProjectName = $state<string | null>(null);
  let uploadInput = $state<HTMLInputElement>();
  let hasLoadError = $state(false);
  let viewMode = $state<'tile' | 'list'>('tile');
  let currentFolder = $state<ProjectFolderViewModel | null>(null);
  let currentFolderTrail = $state<ProjectFolderViewModel[]>([]);
  let currentFolderHash = $state<string | null>(null);
  let currentVirtualPath = $state<string | null>(null);
  let folderHashes = $state(new Map<string, string>());
  let activeRemoteFullscreen = $state<VirtualRemoteFullscreenDetail | null>(null);
  let activeRemoteGenericFile = $state<{ sourceId: string; path: string; filename: string; sizeBytes?: number } | null>(null);
  let activeRemoteImage = $state<{ sourceId: string; path: string; filename: string; sizeBytes?: number; src: string } | null>(null);
  let remoteDownloadProgress = $state<{ sourceId: string; path: string; downloadedBytes: number; totalBytes: number } | null>(null);
  let remoteDownloadController: AbortController | null = null;
  let remoteImageUrls = $state<Record<string, string>>({});
  let activeStoredFullscreen = $state<EmbedFullscreenDispatchDetail | null>(null);
  let projectHashId = $state<string | null>(null);
  let activeRemoteSourceId = $state<string | null>(null);
  let remotePath = $state('.');
  let remotePathParts = $derived(remotePath.split('/').filter((part) => part && part !== '.'));
  let remoteEntries = $state<ProjectRemoteDirectoryEntry[]>([]);
  let remotePageIndex = $state(0);
  let remotePageCursors = $state<(string | null)[]>([null]);
  let remoteNextCursor = $state<string | null>(null);
  let remoteLegacyEntries = $state<{ sourceId: string; path: string; entries: ProjectRemoteDirectoryEntry[]; omitted: number } | null>(null);
  let remoteRootEntries = $state<Record<string, ProjectRemoteDirectoryEntry[]>>({});
  let remoteRootOmitted = $state<Record<string, number>>({});
  let remoteRootPreviewStatus = $state<Record<string, 'loading' | 'unavailable'>>({});
  let rootPrefetchVersion = $state(0);
  let rootPrefetchController: AbortController | null = null;
  let rootPrefetchInFlight = false;
  let rootPrefetchCount = 0;
  let rootPrefetchEpoch = 0;
  const rootPrefetchKeys = new Set<string>();
  let projectSearchResults = $state<ProjectFileSearchEntry[]>([]);
  let projectSearchActive = $state(false);
  let projectSearchLoading = $state(false);
  let projectSearchError = $state('');
  let projectSearchOmitted = $state(0);
  let searchPageIndex = $state(0);
  let projectSearchController: AbortController | null = null;
  let projectSearchTimer: ReturnType<typeof setTimeout> | null = null;
  let projectSearchGeneration = 0;
  let remoteOmittedCount = $state(0);
  let remotePreviewEntries = $state<RemotePreviewEntry[]>([]);
  let remoteError = $state('');
  let remoteNeedsSignIn = $state(false);
  let isRemoteLoading = $state(false);
  let remoteRequestController: AbortController | null = null;
  let remoteRequestGeneration = 0;
  let activeTab = $state<ProjectTab>('overview');
  let readmeState = $state<ProjectReadmeState>({ status: 'loading' });
  let pageDisposed = false;

  function replaceReadmeState(next: ProjectReadmeState): void {
    if (readmeState.status === 'ready' && readmeState.document !== (next.status === 'ready' ? next.document : null)) {
      releaseProjectReadmeImages(readmeState.document);
    }
    readmeState = next;
  }

  function defaultConnectedSource(sourceList: ProjectSourceViewModel[]): ProjectSourceViewModel | null {
    const connected = sourceList.filter((source) => source.status === 'connected');
    return connected.find((source) => source.source_type === 'local_git_repository')
      ?? (connected.length === 1 ? connected[0] : null);
  }
  let folderSearchQuery = $state('');
  let storedPageIndex = $state(0);
  let sortNewestFirst = $state(true);
  let showCreateMenu = $state(false);
  let workspaceWidth = $state(0);
  let projectMainElement = $state<HTMLElement>();
  let autoBrowsedProjectId: string | null = null;
  let viewerSplitOpen = $derived(workspaceWidth >= 1024 && (!!activeRemoteFullscreen || !!activeRemoteGenericFile || !!activeRemoteImage || !!activeStoredFullscreen));

  // Open the connected repository directly; its directory is the Files view.
  $effect(() => {
    if (activeTab !== 'folders' || !selectedProject || activeRemoteSourceId || currentFolder || currentVirtualPath) return;
    if (!previewState?.remoteEntries && !previewState?.legacyRemoteEntries && !$userProfile.user_id) return;
    if (autoBrowsedProjectId === selectedProject.project_id) return;
    const source = defaultConnectedSource(sources);
    if (source) {
      autoBrowsedProjectId = selectedProject.project_id;
      void browseRemoteSource(source);
    }
  });

  $effect(() => {
    void rootPrefetchVersion;
    const project = selectedProject;
    const ownerId = $userProfile.user_id;
    if (activeTab !== 'folders' || !project || (!previewState?.remoteEntries && !previewState?.legacyRemoteEntries && !ownerId) || rootPrefetchInFlight) return;
    const autoSource = defaultConnectedSource(sources);
    const remaining = Math.max(0, 12 - rootPrefetchCount);
    const candidates = sources.filter((source) => source.status === 'connected'
      && (activeRemoteSourceId === null || source.source_id !== autoSource?.source_id)
      && !rootPrefetchKeys.has(`${project.project_id}:${source.source_id}`)).slice(0, remaining);
    if (candidates.length === 0) return;
    for (const source of candidates) rootPrefetchKeys.add(`${project.project_id}:${source.source_id}`);
    rootPrefetchCount += candidates.length;
    void prefetchRemoteRoots(project, ownerId, candidates);
  });

  $effect(() => {
    if (!viewerSplitOpen || activeTab !== 'folders') return;
    const frame = requestAnimationFrame(() => {
      const actions = projectMainElement?.querySelector<HTMLElement>('[data-testid="project-folder-actions"]');
      if (!actions || !projectMainElement) return;
      projectMainElement.scrollTop += actions.getBoundingClientRect().top
        - projectMainElement.getBoundingClientRect().top - 12;
    });
    return () => cancelAnimationFrame(frame);
  });

  setContext<EmbedChatContext>(EMBED_CHAT_CONTEXT, {
    get showChatButton() { return false; },
    get isSplitPane() { return viewerSplitOpen; },
    get presentedEmbedId() { return activeRemoteFullscreen?.embedId ?? activeStoredFullscreen?.embedId ?? null; },
    get resolvedEmbedId() { return activeRemoteFullscreen?.embedId ?? activeStoredFullscreen?.embedId ?? null; },
    onShowChat: () => undefined,
  });

  let sortedProjects = $derived([...projects].sort((a, b) => (b.encrypted.created_at || 0) - (a.encrypted.created_at || 0)));
  let recentProjects = $derived(sortedProjects.slice(0, 8));
  let greetingName = $derived($userProfile.username || 'there');
  let virtualBrowserView = $derived(projectVirtualBrowserView(items, currentVirtualPath));
  let virtualFolderTrail = $derived(projectVirtualBreadcrumbs(currentVirtualPath));
  let browserFolders = $derived(!activeRemoteSourceId && currentVirtualPath === null
    ? folders.filter((folder) => (folder.parentHash ?? null) === currentFolderHash)
    : []);
  let browserVirtualFolders = $derived(!activeRemoteSourceId && currentFolderHash === null ? virtualBrowserView.folders : []);
  let browserItems = $derived(activeRemoteSourceId ? [] : currentFolderHash === null
    ? virtualBrowserView.items
    : items.filter((item) => (item.encrypted.hashed_folder_id ?? null) === currentFolderHash));
  let browserSources = $derived(!activeRemoteSourceId && currentFolderHash === null && currentVirtualPath === null ? sources : []);
  let projectLandingItems = $derived<ProjectContinueItem[]>(recentProjects.map((project) => ({
    id: project.project_id,
    title: project.name || 'Untitled project',
    category: 'productivity',
    appId: 'projects',
    icon: 'folder',
    source: 'recent',
  })));
  const projectTabs = [
    { id: 'overview', icon: 'project', label: 'Overview' },
    { id: 'folders', icon: 'files', label: 'Files' },
    { id: 'tasks', icon: 'projectmanagement', label: 'Tasks' },
  ];
  let normalizedFolderSearch = $derived(folderSearchQuery.trim().toLocaleLowerCase());
  let visibleBrowserFolders = $derived(sortEntries(
    browserFolders.filter((folder) => !normalizedFolderSearch || (folder.name || 'Untitled folder').toLocaleLowerCase().includes(normalizedFolderSearch)),
    (folder) => folder.encrypted.updated_at || folder.encrypted.created_at,
    (folder) => folder.name || 'Untitled folder',
  ));
  let visibleVirtualFolders = $derived(sortEntries(
    browserVirtualFolders.filter((folder) => !normalizedFolderSearch || folder.name.toLocaleLowerCase().includes(normalizedFolderSearch)),
    (folder) => virtualFolderTimestamp(folder),
    (folder) => folder.name,
  ));
  let visibleBrowserItems = $derived(sortEntries(
    browserItems.filter((item) => !normalizedFolderSearch || projectBrowserItemName(item).toLocaleLowerCase().includes(normalizedFolderSearch)),
    (item) => item.encrypted.updated_at || item.encrypted.created_at,
    projectBrowserItemName,
  ));
  let visibleBrowserSources = $derived(sortEntries(
    browserSources.filter((source) => !normalizedFolderSearch || (source.displayName || source.source_id).toLocaleLowerCase().includes(normalizedFolderSearch)),
    (source) => source.encrypted.updated_at || source.encrypted.created_at,
    (source) => source.displayName || source.source_id,
  ));
  let currentSearchResults = $derived(projectSearchResults.filter(isCurrentFolderSearchResult));
  let acrossSearchResults = $derived(projectSearchResults.filter((entry) => !isCurrentFolderSearchResult(entry)));
  let orderedSearchResults = $derived([...currentSearchResults, ...acrossSearchResults]);
  let searchPageResults = $derived(orderedSearchResults.slice(searchPageIndex * FILES_PAGE_SIZE, (searchPageIndex + 1) * FILES_PAGE_SIZE));
  let searchPageCurrent = $derived(searchPageResults.filter(isCurrentFolderSearchResult));
  let searchPageAcross = $derived(searchPageResults.filter((entry) => !isCurrentFolderSearchResult(entry)));
  let storedEntryCount = $derived(visibleBrowserFolders.length + visibleVirtualFolders.length + visibleBrowserItems.length + visibleBrowserSources.length);
  $effect(() => {
    if (storedPageIndex > 0 && storedPageIndex * FILES_PAGE_SIZE >= storedEntryCount) {
      storedPageIndex = Math.max(0, Math.ceil(storedEntryCount / FILES_PAGE_SIZE) - 1);
    }
  });
  let storedPageStart = $derived(storedPageIndex * FILES_PAGE_SIZE);
  let pageBrowserFolders = $derived(pageEntries(visibleBrowserFolders, storedPageStart, 0));
  let pageVirtualFolders = $derived(pageEntries(visibleVirtualFolders, storedPageStart, visibleBrowserFolders.length));
  let pageBrowserItems = $derived(pageEntries(visibleBrowserItems, storedPageStart, visibleBrowserFolders.length + visibleVirtualFolders.length));
  let pageBrowserSources = $derived(pageEntries(visibleBrowserSources, storedPageStart, visibleBrowserFolders.length + visibleVirtualFolders.length + visibleBrowserItems.length));
  let activeRemoteSource = $derived(sources.find((source) => source.source_id === activeRemoteSourceId) ?? null);
  let remoteEntryCount = $derived(remotePageIndex * FILES_PAGE_SIZE + remoteEntries.length + remoteOmittedCount);
  let activeRemoteImportEntry = $derived(remotePreviewEntries.find((entry) =>
    entry.preview.embed.embed_id === activeRemoteFullscreen?.embedId && entry.canImport
    && entry.readResult && !entry.preview.embed.content.safety_flags.includes('truncated')
    && entry.preview.embed.content.preview_policy !== 'unsupported_binary') ?? null);

  async function importActiveRemotePreview(): Promise<void> {
    if (!activeRemoteImportEntry || isSaving) return;
    await handleUploadRemotePreview(activeRemoteImportEntry);
  }
  let visibleRemoteEntries = $derived(remoteEntries.filter((entry) => !normalizedFolderSearch || entry.path.split('/').at(-1)?.toLocaleLowerCase().includes(normalizedFolderSearch)));

  function pageEntries<T>(entries: T[], start: number, preceding: number): T[] {
    return entries.slice(Math.max(0, start - preceding), Math.max(0, start + FILES_PAGE_SIZE - preceding));
  }

  function directParentPath(path: string): string {
    const parts = path.split('/').filter(Boolean);
    return parts.length > 1 ? parts.slice(0, -1).join('/') : '.';
  }

  function isCurrentFolderSearchResult(entry: ProjectFileSearchEntry): boolean {
    if (entry.kind === 'remote') {
      return entry.sourceId === activeRemoteSourceId && directParentPath(entry.path) === remotePath;
    }
    if (activeRemoteSourceId) return false;
    if (entry.kind === 'folder') return currentVirtualPath === null && (entry.folder.parentHash ?? null) === currentFolderHash;
    if (entry.kind === 'virtual-folder') return currentFolderHash === null && directParentPath(entry.folder.path) === (currentVirtualPath ?? '.');
    if (currentFolderHash !== null) return (entry.item.encrypted.hashed_folder_id ?? null) === currentFolderHash;
    if (entry.item.encrypted.hashed_folder_id) return false;
    const path = entry.item.metadata.source === 'hosted_project_file' && typeof entry.item.metadata.path === 'string'
      ? entry.item.metadata.path : null;
    return path ? directParentPath(path) === (currentVirtualPath ?? '.') : currentVirtualPath === null;
  }

  function searchResultName(entry: ProjectFileSearchEntry): string {
    if (entry.kind === 'remote') return entry.path.split('/').at(-1) || entry.path;
    if (entry.kind === 'folder') return entry.folder.name || 'Untitled folder';
    if (entry.kind === 'virtual-folder') return entry.folder.name;
    return projectBrowserItemName(entry.item);
  }

  function searchResultKey(entry: ProjectFileSearchEntry): string {
    if (entry.kind === 'remote') return `remote:${entry.sourceId}:${entry.path}`;
    if (entry.kind === 'folder') return `folder:${entry.folder.folder_id}`;
    if (entry.kind === 'virtual-folder') return `virtual:${entry.folder.path}`;
    return `item:${entry.item.project_item_id}`;
  }

  function cancelProjectSearch(clear = true): void {
    if (projectSearchTimer !== null) clearTimeout(projectSearchTimer);
    projectSearchTimer = null;
    projectSearchController?.abort();
    projectSearchController = null;
    projectSearchGeneration += 1;
    projectSearchLoading = false;
    if (!clear) return;
    projectSearchActive = false;
    projectSearchResults = [];
    projectSearchError = '';
    projectSearchOmitted = 0;
    searchPageIndex = 0;
  }

  function handleFolderSearchInput(): void {
    cancelProjectSearch();
    storedPageIndex = 0;
    if (!folderSearchQuery.trim()) return;
    // One search after typing pauses avoids a remote request for every keystroke.
    projectSearchTimer = setTimeout(() => void searchProjectFiles(), 600);
  }

  function localProjectSearchResults(query: string): ProjectFileSearchEntry[] {
    const found: ProjectFileSearchEntry[] = [];
    for (const folder of folders) {
      if ((folder.name || 'Untitled folder').toLocaleLowerCase().includes(query)) found.push({ kind: 'folder', folder });
    }
    const virtualFolders = new Map<string, ProjectVirtualFolder>();
    for (const item of items) {
      if (projectBrowserItemName(item).toLocaleLowerCase().includes(query)) found.push({ kind: 'item', item });
      if (item.metadata.source !== 'hosted_project_file' || typeof item.metadata.path !== 'string') continue;
      const parts = item.metadata.path.split('/');
      if (parts.some((part) => !part || part === '.' || part === '..') || parts.length > 64) continue;
      for (let index = 0; index < parts.length - 1; index += 1) {
        const name = parts[index];
        if (!name?.toLocaleLowerCase().includes(query)) continue;
        const path = parts.slice(0, index + 1).join('/');
        virtualFolders.set(path, { name, path });
      }
    }
    for (const folder of virtualFolders.values()) found.push({ kind: 'virtual-folder', folder });
    return found;
  }

  async function searchProjectFiles(): Promise<void> {
    const project = selectedProject;
    const query = folderSearchQuery.trim();
    if (!project || !query) { cancelProjectSearch(); return; }
    cancelProjectSearch();
    const generation = projectSearchGeneration;
    const controller = new AbortController();
    projectSearchController = controller;
    projectSearchActive = true;
    projectSearchLoading = true;
    remoteNeedsSignIn = false;
    projectSearchResults = localProjectSearchResults(query.toLocaleLowerCase());
    storedPageIndex = 0;
    const remoteSources = sources.filter((source) => source.status === 'connected');
    try {
      for (let offset = 0; offset < remoteSources.length; offset += 2) {
        if (controller.signal.aborted) return;
        const batch = await Promise.allSettled(remoteSources.slice(offset, offset + 2).map(async (source) => {
          if (previewState?.remoteEntries || previewState?.legacyRemoteEntries) {
            const matches = (previewState.remoteEntries ?? previewState.legacyRemoteEntries ?? [])
              .filter((entry) => entry.path.split('/').at(-1)?.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
              .sort((left, right) => {
                const leftCurrent = source.source_id === activeRemoteSourceId && directParentPath(left.path) === remotePath;
                const rightCurrent = source.source_id === activeRemoteSourceId && directParentPath(right.path) === remotePath;
                return Number(rightCurrent) - Number(leftCurrent) || left.path.localeCompare(right.path);
              });
            return { source, result: { matches: matches.slice(0, 100).map((entry) => ({ path: entry.path, kind: entry.kind })), omitted: Math.max(0, matches.length - 100), excluded: 0 } as ProjectRemoteSearchResult };
          }
          return { source, result: await requestProjectRemoteAccess<ProjectRemoteSearchResult>(
            project, source,
            { ownerId: $userProfile.user_id || '', teamId: getActiveTeamContextSnapshot().teamId },
            'search', { query, target: 'files', mode: 'literal', path: '.', max_results: 100,
              ...(source.source_id === activeRemoteSourceId ? { priority_path: remotePath } : {}) }, controller.signal,
          ) };
        }));
        if (controller.signal.aborted || generation !== projectSearchGeneration || selectedProject?.project_id !== project.project_id) return;
        const found = new Map(projectSearchResults.map((entry) => [searchResultKey(entry), entry]));
        for (const settled of batch) {
          if (settled.status === 'rejected') {
            if (!(settled.reason instanceof DOMException && settled.reason.name === 'AbortError')) {
              projectSearchError = 'Some connected sources could not be searched.';
              if (settled.reason instanceof ProjectRemoteAccessError && settled.reason.code === 'requester_device_identity_unavailable') remoteNeedsSignIn = true;
            }
            continue;
          }
          projectSearchOmitted += settled.value.result.omitted;
          for (const match of settled.value.result.matches) {
            const entry: ProjectFileSearchEntry = { kind: 'remote', sourceId: settled.value.source.source_id,
              path: match.path, entryKind: match.kind ?? 'file' };
            found.set(searchResultKey(entry), entry);
          }
        }
        projectSearchResults = [...found.values()].sort((left, right) => searchResultName(left).localeCompare(searchResultName(right)));
      }
    } finally {
      if (generation === projectSearchGeneration) {
        projectSearchLoading = false;
        projectSearchController = null;
      }
    }
  }

  async function scrollToFilesStart(): Promise<void> {
    await tick();
    projectMainElement?.querySelector<HTMLElement>('[data-testid="project-browser-list"]')?.scrollIntoView({ block: 'start' });
  }

  function showStoredPage(index: number): void {
    if (index < 0 || index * FILES_PAGE_SIZE >= storedEntryCount) return;
    storedPageIndex = index;
    void scrollToFilesStart();
  }

  async function showRemotePage(index: number): Promise<void> {
    if (!activeRemoteSource || index < 0 || (index > remotePageIndex && !remoteNextCursor)) return;
    await browseRemoteSource(activeRemoteSource, remotePath, index);
    await scrollToFilesStart();
  }

  function virtualFolderTimestamp(folder: ProjectVirtualFolder): number {
    const prefix = `${folder.path}/`;
    return items.reduce((latest, item) => {
      const path = typeof item.metadata.path === 'string' ? item.metadata.path : '';
      if (!path.startsWith(prefix)) return latest;
      return Math.max(latest, item.encrypted.updated_at || item.encrypted.created_at || 0);
    }, 0);
  }

  function sortEntries<T>(entries: T[], timestamp: (entry: T) => number, label: (entry: T) => string): T[] {
    return [...entries].sort((a, b) => {
      const byTime = timestamp(b) - timestamp(a);
      if (byTime !== 0) return sortNewestFirst ? byTime : -byTime;
      return label(a).localeCompare(label(b));
    });
  }

  function remoteFileSizeLabel(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  }

  function remoteFolderStatus(entry: Pick<ProjectRemoteDirectoryEntry,
    'childFileCount' | 'childFolderCount' | 'childFileSizeBytes' | 'childSummaryTruncated'>): string {
    if (entry.childFileCount === undefined) return 'Contents unavailable';
    const approximate = entry.childSummaryTruncated ? 'At least ' : '';
    const files = `${approximate}${entry.childFileCount} ${entry.childFileCount === 1 ? 'file' : 'files'}`;
    const folders = entry.childFolderCount ? `, ${entry.childFolderCount} ${entry.childFolderCount === 1 ? 'folder' : 'folders'}` : '';
    const size = entry.childFileSizeBytes === undefined ? '' : ` · ${entry.childSummaryTruncated ? 'at least ' : ''}${remoteFileSizeLabel(entry.childFileSizeBytes)} in files`;
    return `${files}${folders}${size}`;
  }

  function remoteRootStatus(sourceId: string): string {
    const entries = remoteRootEntries[sourceId];
    if (!entries) return remoteRootPreviewStatus[sourceId] === 'loading' ? 'Loading folder preview…'
      : remoteRootPreviewStatus[sourceId] === 'unavailable' ? 'Contents unavailable' : 'Open to view contents';
    const files = entries.filter((entry) => entry.kind === 'file');
    return remoteFolderStatus({
      childFileCount: files.length,
      childFolderCount: entries.filter((entry) => entry.kind === 'directory').length,
      childFileSizeBytes: files.every((entry) => entry.sizeBytes !== undefined)
        ? files.reduce((total, entry) => total + (entry.sizeBytes ?? 0), 0) : undefined,
      childSummaryTruncated: (remoteRootOmitted[sourceId] ?? 0) > 0,
    });
  }

  function remoteRootChildren(sourceId: string): ProjectRemoteDirectoryEntry[] {
    return [...(remoteRootEntries[sourceId] ?? [])]
      .sort((a, b) => a.kind === b.kind ? a.path.localeCompare(b.path) : a.kind === 'directory' ? -1 : 1)
      .slice(0, 3);
  }

  function folderCardEntries(folder: ProjectFolderViewModel): Array<{ name: string; kind: 'folder' | 'file'; detail: string }> {
    const previewEntries = previewState?.folderCardContents?.[folder.folder_id];
    if (previewEntries) return previewEntries.map((entry) => ({ ...entry, detail: entry.detail || (entry.kind === 'folder' ? 'Folder' : 'File') }));
    const folderHash = folderHashes.get(folder.folder_id);
    if (!folderHash) return [];
    const childFolders = folders
      .filter((candidate) => candidate.parentHash === folderHash)
      .map((candidate) => ({ name: candidate.name || 'Untitled folder', kind: 'folder' as const, detail: 'Folder' }));
    const childItems = items
      .filter((item) => (item.encrypted.hashed_folder_id ?? null) === folderHash)
      .map((item) => ({
        name: projectBrowserItemName(item),
        kind: 'file' as const,
        detail: typeof item.metadata.size_label === 'string' ? item.metadata.size_label : item.item_type,
      }));
    return [...childFolders, ...childItems];
  }

  const PROJECT_SELECTED_EVENT = 'openmates-project-selected';

  function stripHashPrefix(hash: string): string {
    if (!hash) return '';
    return hash.startsWith('#/') ? hash.slice(2) : hash.replace(/^#/, '');
  }

  function parseHashParams(hash: string): URLSearchParams {
    const fragment = stripHashPrefix(hash);
    if (!fragment || fragment === 'settings' || fragment.startsWith('settings/')) {
      return new URLSearchParams();
    }
    return new URLSearchParams(fragment);
  }

  function serializeHashParams(params: URLSearchParams): string {
    const pairs: string[] = [];
    params.forEach((value, key) => {
      pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(value).replace(/%2F/g, '/').replace(/%3A/g, ':')}`);
    });
    return pairs.length > 0 ? `#${pairs.join('&')}` : '';
  }

  function readProjectHashId(hash: string): string | null {
    return parseHashParams(hash).get(PROJECT_ID_HASH_PARAM)?.trim() || null;
  }

  function syncProjectHashFromLocation(): void {
    projectHashId = readProjectHashId(window.location.hash);
  }

  function projectStateHash(projectId: string | null, baseHash = ''): string {
    const params = parseHashParams(baseHash);
    params.delete('workflows');
    params.delete('projects');
    params.delete('tasks');
    params.delete('workflow-id');
    params.delete('workflow-tab');
    params.delete('run-id');
    params.delete('task-id');
    params.delete(PROJECT_ID_HASH_PARAM);
    if (projectId) {
      const routeParams = new URLSearchParams();
      routeParams.set(PROJECT_ID_HASH_PARAM, projectId);
      params.forEach((value, key) => routeParams.append(key, value));
      return serializeHashParams(routeParams);
    }
    const preservedHash = serializeHashParams(params);
    return `#projects${preservedHash ? `&${preservedHash.slice(1)}` : ''}`;
  }

  function projectStateHref(projectId: string): string {
    return `${PROJECTS_ROUTE}${projectStateHash(projectId)}`;
  }

  function setProjectUrlState(projectId: string | null, replaceHistory = false): void {
    const nextHash = projectStateHash(projectId, window.location.hash);
    projectHashId = readProjectHashId(nextHash);
    if (window.location.pathname === PROJECTS_ROUTE && window.location.hash === nextHash) return;
    if (replaceHistory) {
      replaceState(`${PROJECTS_ROUTE}${nextHash}`, {});
    } else {
      pushState(`${PROJECTS_ROUTE}${nextHash}`, {});
    }
  }

  function broadcastProjectSelected(project: ProjectViewModel): void {
    window.dispatchEvent(new CustomEvent<ProjectViewModel>(PROJECT_SELECTED_EVENT, { detail: project }));
  }

  async function refreshProjects(): Promise<void> {
    isLoading = true;
    try {
      hasLoadError = false;
      projects = await listProjects();
      if (selectedProject) {
        selectedProject = projects.find((project) => project.project_id === selectedProject?.project_id) ?? selectedProject;
      }
    } catch (error) {
      hasLoadError = true;
      console.error('[ProjectsPage] Failed to load projects:', error);
      notificationStore.error('Failed to load projects');
    } finally {
      isLoading = false;
    }
  }

  async function refreshSelectedProject(): Promise<void> {
    if (!selectedProject) {
      folders = [];
      items = [];
      sources = [];
      currentFolder = null;
      currentFolderTrail = [];
      currentFolderHash = null;
      currentVirtualPath = null;
      folderHashes = new Map();
      replaceReadmeState({ status: 'loading' });
      resetRemoteBrowser();
      return;
    }
    const project = selectedProject;
    replaceReadmeState({ status: 'loading' });
    const [contents, projectSources] = await Promise.all([
      getProjectContents(project),
      listProjectSources(project),
    ]);
    if (selectedProject?.project_id !== project.project_id) return;
    folders = contents.folders;
    items = contents.items;
    sources = projectSources;
    folderHashes = new Map(await Promise.all(contents.folders.map(async (folder) => [folder.folder_id, await computeSHA256(folder.folder_id)] as const)));
    if (currentFolder && !contents.folders.some((folder) => folder.folder_id === currentFolder?.folder_id)) {
      currentFolder = null;
      currentFolderTrail = [];
      currentFolderHash = null;
    }
    const loadedReadme = await loadProjectReadme({
      project,
      items: contents.items,
      sources: projectSources,
      remoteContext: {
        ownerId: $userProfile.user_id || '',
        teamId: getActiveTeamContextSnapshot().teamId,
      },
    });
    if (pageDisposed || selectedProject?.project_id !== project.project_id) {
      if (loadedReadme.status === 'ready') releaseProjectReadmeImages(loadedReadme.document);
      return;
    }
    replaceReadmeState(loadedReadme);
  }

  async function retryProjectReadme(): Promise<void> {
    try {
      await refreshSelectedProject();
    } catch (error) {
      console.error('[ProjectsPage] Failed to retry the project overview:', error);
      replaceReadmeState({ status: 'error', message: 'Could not load the project overview. Please try again.' });
    }
  }

  function clearSelectedProject(): void {
    selectedProject = null;
    folders = [];
    items = [];
    sources = [];
    currentFolder = null;
    currentFolderTrail = [];
    currentFolderHash = null;
    currentVirtualPath = null;
    folderHashes = new Map();
    activeTab = 'overview';
    replaceReadmeState({ status: 'loading' });
    resetRemoteBrowser();
  }

  async function selectProject(project: ProjectViewModel, updateHash = true): Promise<void> {
    selectedProject = project;
    activeTab = 'overview';
    currentFolder = null;
    currentFolderTrail = [];
    currentFolderHash = null;
    currentVirtualPath = null;
    resetRemoteBrowser();
    broadcastProjectSelected(project);
    if (updateHash) setProjectUrlState(project.project_id);
    if (variant === 'sidebar') panelState.closeChats();
    await refreshSelectedProject();
  }

  async function selectProjectById(projectId: string, updateHash = true): Promise<void> {
    const project = projects.find((candidate) => candidate.project_id === projectId);
    if (project) {
      await selectProject(project, updateHash);
      return;
    }

    try {
      const loadedProject = await getProject(projectId);
      projects = [loadedProject, ...projects.filter((candidate) => candidate.project_id !== projectId)];
      await selectProject(loadedProject, updateHash);
    } catch (error) {
      console.error('[ProjectsPage] Failed to open project from hash:', error);
      notificationStore.error('Failed to open project');
      if (!updateHash) {
        clearSelectedProject();
        setProjectUrlState(null, true);
      }
    }
  }

  function openProjectsHome(): void {
    clearSelectedProject();
    setProjectUrlState(null);
  }

  async function openProjectFromCard(item: ProjectContinueItem): Promise<void> {
    await selectProjectById(item.id);
  }

  function requestProjectCreation(): void {
    const name = newProjectName.trim();
    if (!name || isSaving) return;
    pendingProjectName = name;
    newProjectWriteMode = null;
  }

  function cancelProjectCreation(): void {
    pendingProjectName = null;
    newProjectWriteMode = null;
  }

  async function handleCreateProject(): Promise<void> {
    const name = pendingProjectName?.trim() ?? '';
    if (!name || !newProjectWriteMode || isSaving) return;
    isSaving = true;
    try {
      const project = await createProject(name, newProjectWriteMode);
      projects = [project, ...projects];
      selectedProject = project;
      currentFolder = null;
      currentFolderTrail = [];
      currentFolderHash = null;
      currentVirtualPath = null;
      folders = [];
      items = [];
      sources = [];
      newProjectName = '';
      newProjectWriteMode = null;
      pendingProjectName = null;
      setProjectUrlState(project.project_id);
      broadcastProjectFilesChanged(project.project_id);
      broadcastProjectSelected(project);
      notificationStore.success('Project created');
    } catch (error) {
      console.error('[ProjectsPage] Failed to create project:', error);
      notificationStore.error('Failed to create project');
    } finally {
      isSaving = false;
    }
  }

  async function handleDeleteProject(project: ProjectViewModel): Promise<void> {
    if (!confirm(`Delete project "${project.name}"? This removes the project organization, not the original chats or embeds.`)) return;
    try {
      await deleteProject(project.project_id);
      projects = projects.filter((candidate) => candidate.project_id !== project.project_id);
      if (selectedProject?.project_id === project.project_id) {
        clearSelectedProject();
        setProjectUrlState(null);
      }
      broadcastProjectFilesChanged(project.project_id);
      notificationStore.success('Project deleted');
    } catch (error) {
      console.error('[ProjectsPage] Failed to delete project:', error);
      notificationStore.error('Failed to delete project');
    }
  }

  function updateProjectInList(project: ProjectViewModel): void {
    projects = projects.map((candidate) => candidate.project_id === project.project_id ? project : candidate);
  }

  async function saveSelectedProjectTitle(title: string): Promise<void> {
    if (!selectedProject) return;
    const updatedProject = await updateProjectMetadata(selectedProject, { name: title });
    selectedProject = updatedProject;
    updateProjectInList(updatedProject);
    broadcastProjectFilesChanged(updatedProject.project_id);
  }

  async function saveSelectedProjectDescription(description: string): Promise<void> {
    if (!selectedProject) return;
    const updatedProject = await updateProjectMetadata(selectedProject, { description });
    selectedProject = updatedProject;
    updateProjectInList(updatedProject);
    broadcastProjectFilesChanged(updatedProject.project_id);
  }

  async function handleUploadSelected(event: Event): Promise<void> {
    if (!selectedProject) return;
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    isSaving = true;
    try {
      await uploadFileToProject(selectedProject, file, {}, { folderId: currentFolder?.folder_id ?? null });
      await refreshSelectedProject();
      notificationStore.success('File uploaded to project');
    } catch (error) {
      console.error('[ProjectsPage] Failed to upload file to project:', error);
      notificationStore.error('Failed to upload file to project');
    } finally {
      isSaving = false;
      input.value = '';
    }
  }

  async function handleUploadRemotePreview(entry: RemotePreviewEntry): Promise<void> {
    const project = selectedProject;
    if (!project || !entry.canImport || isSaving) return;
    isSaving = true;
    try {
      let readResult = entry.readResult;
      if (!readResult) {
        const source = sources.find((candidate) => candidate.source_id === entry.preview.embed.content.source_id);
        if (!source || !$userProfile.user_id) throw new Error('Connected source is unavailable');
        const request = beginRemoteRequest();
        let result: ProjectRemoteTextResult;
        try {
          result = await requestProjectRemoteAccess<ProjectRemoteTextResult>(
            project,
            source,
            { ownerId: $userProfile.user_id, teamId: getActiveTeamContextSnapshot().teamId },
            'read_text',
            { path: entry.preview.embed.content.path },
            request.controller.signal,
          );
        } finally {
          finishRemoteRequest(request);
        }
        const currentSource = sources.find((candidate) => candidate.source_id === source.source_id);
        if (!isCurrentRemoteRequest(request, source.source_id) || currentSource?.status !== 'connected') {
          throw new DOMException('Remote file read was superseded', 'AbortError');
        }
        if (selectedProject?.project_id !== project.project_id) throw new Error('Project changed before import completed');
        if (result.truncated) throw new Error('Import requires a complete, non-truncated file read');
        readResult = result;
      }
      const candidate = buildRemoteFileUploadCandidate({
        preview: entry.preview,
        readResult,
      });
      await uploadFileToProject(project, candidate.file, candidate.metadata, { folderId: currentFolder?.folder_id ?? null });
      await refreshSelectedProject();
      notificationStore.success('Remote file uploaded to OpenMates');
    } catch (error) {
      console.error('[ProjectsPage] Failed to upload remote preview to project:', error);
      notificationStore.error('Failed to upload remote file');
    } finally {
      isSaving = false;
    }
  }

  function remoteFullscreenDetail(
    preview: VirtualRemoteFilePreview,
    content: string,
    sourceLabel: string,
  ): VirtualRemoteFullscreenDetail {
    const detail = buildVirtualRemoteFullscreenDetail(preview, content);
    const remoteSourceLabel = sourceLabel.trim().slice(0, 256);
    return {
      ...detail,
      embedData: {
        ...detail.embedData,
        content: { ...detail.embedData.content, remote_source_label: remoteSourceLabel },
      },
      decodedContent: { ...detail.decodedContent, remote_source_label: remoteSourceLabel },
    };
  }

  async function openRemotePreview(preview: VirtualRemoteFilePreview): Promise<void> {
    const entry = remotePreviewEntries.find((candidate) => candidate.preview.embed.embed_id === preview.embed.embed_id);
    if (entry?.readResult) {
      activeRemoteFullscreen = remoteFullscreenDetail(preview, entry.readResult.content, entry.sourceLabel);
      return;
    }
    const source = sources.find((candidate) => candidate.source_id === preview.embed.content.source_id);
    if (!source) {
      remoteError = 'Connected source is unavailable';
      return;
    }
    await openRemoteFile(source, preview.embed.content.path);
  }

  function openRemoteGenericFile(source: ProjectSourceViewModel, path: string, sizeBytes?: number): void {
    activeRemoteFullscreen = null;
    activeRemoteGenericFile = null;
    activeRemoteImage = null;
    activeRemoteGenericFile = {
      sourceId: source.source_id,
      path,
      filename: path.split('/').filter(Boolean).pop() || path,
      sizeBytes,
    };
  }

  async function openRemoteFileDetails(source: ProjectSourceViewModel, path: string, sizeBytes?: number): Promise<void> {
    if (!/\.(png|jpe?g|gif|webp|avif)$/i.test(path) || (sizeBytes !== undefined && sizeBytes > 2 * 1024 * 1024)) {
      openRemoteGenericFile(source, path, sizeBytes);
      return;
    }
    const key = `${source.source_id}:${path}`;
    let src = remoteImageUrls[key];
    if (!src) {
      const project = selectedProject;
      if (!project || !$userProfile.user_id) return;
      const request = beginRemoteRequest();
      isRemoteLoading = true;
      try {
        src = await readConnectedProjectImage(project, source,
          { ownerId: $userProfile.user_id, teamId: getActiveTeamContextSnapshot().teamId }, path, request.controller.signal) ?? '';
        if (!isCurrentRemoteRequest(request, source.source_id)) {
          if (src) URL.revokeObjectURL(src);
          return;
        }
        if (src) {
          const next = { ...remoteImageUrls };
          if (Object.keys(next).length >= 8) {
            const oldest = Object.keys(next)[0];
            if (oldest) {
              URL.revokeObjectURL(next[oldest]);
              delete next[oldest];
            }
          }
          remoteImageUrls = { ...next, [key]: src };
        }
      } catch {
        if (!isCurrentRemoteRequest(request, source.source_id)) return;
      } finally {
        finishRemoteRequest(request);
      }
    }
    if (!src) {
      openRemoteGenericFile(source, path, sizeBytes);
      return;
    }
    activeRemoteFullscreen = null;
    activeRemoteGenericFile = null;
    activeRemoteImage = { sourceId: source.source_id, path, filename: path.split('/').pop() || path, sizeBytes, src };
  }

  async function downloadRemoteFile(sourceId: string, path: string): Promise<void> {
    if (remoteDownloadController) throw new Error('A connected file download is already in progress');
    const project = selectedProject;
    const source = sources.find((candidate) => candidate.source_id === sourceId);
    if (!project || !source || !$userProfile.user_id) {
      throw new Error('Connected source is unavailable');
    }
    const controller = new AbortController();
    remoteDownloadController = controller;
    remoteDownloadProgress = { sourceId, path, downloadedBytes: 0, totalBytes: 0 };
    try {
      await downloadConnectedProjectFile(project, source,
        { ownerId: $userProfile.user_id, teamId: getActiveTeamContextSnapshot().teamId }, path,
        controller.signal, (downloadedBytes, totalBytes) => {
          if (remoteDownloadController === controller) {
            remoteDownloadProgress = { sourceId, path, downloadedBytes, totalBytes };
          }
        });
    } finally {
      if (remoteDownloadController === controller) {
        remoteDownloadController = null;
        remoteDownloadProgress = null;
      }
    }
  }

  async function downloadRemoteFileOrNotify(sourceId: string, path: string): Promise<void> {
    try {
      await downloadRemoteFile(sourceId, path);
      notificationStore.success('Connected file downloaded');
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      notificationStore.error(error instanceof Error ? error.message : 'Could not download the connected file');
    }
  }

  function cancelRemoteDownload(): void {
    remoteDownloadController?.abort();
  }

  function closeRemotePreview(): void {
    cancelRemoteDownload();
    const closingEmbedId = activeRemoteFullscreen?.embedId;
    activeRemoteFullscreen = null;
    activeRemoteGenericFile = null;
    activeRemoteImage = null;
    if (closingEmbedId) {
      remotePreviewEntries = remotePreviewEntries.map((entry) => entry.preview.embed.embed_id === closingEmbedId
        ? { ...entry, readResult: null }
        : entry);
    }
  }

  function openStoredFullscreen(detail: EmbedFullscreenDispatchDetail): void {
    activeStoredFullscreen = detail;
  }

  function closeStoredFullscreen(): void {
    activeStoredFullscreen = null;
  }

  function storedFullscreenContent(detail: EmbedFullscreenDispatchDetail): Record<string, unknown> {
    return detail.decodedContent && typeof detail.decodedContent === 'object'
      ? detail.decodedContent as Record<string, unknown>
      : {};
  }

  function handleRemoteFullscreenClick(event: MouseEvent): void {
    if (!activeRemoteFullscreen && !activeRemoteGenericFile && !activeRemoteImage) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('[data-testid="embed-minimize"]')) {
      closeRemotePreview();
    }
  }

  function handleRemoteFullscreenKeydown(event: KeyboardEvent): void {
    if ((!activeRemoteFullscreen && !activeRemoteGenericFile && !activeRemoteImage) || event.key !== 'Escape') return;
    closeRemotePreview();
  }

  function resetRemoteBrowser(): void {
    cancelProjectSearch();
    folderSearchQuery = '';
    cancelRemoteDownload();
    autoBrowsedProjectId = null;
    resetRootPrefetch();
    remoteRequestController?.abort();
    remoteRequestController = null;
    remoteRequestGeneration += 1;
    activeRemoteFullscreen = null;
    activeRemoteGenericFile = null;
    activeRemoteImage = null;
    for (const url of Object.values(remoteImageUrls)) URL.revokeObjectURL(url);
    remoteImageUrls = {};
    activeStoredFullscreen = null;
    activeRemoteSourceId = null;
    remotePath = '.';
    remoteEntries = [];
    remotePageIndex = 0;
    remotePageCursors = [null];
    remoteNextCursor = null;
    remoteLegacyEntries = null;
    storedPageIndex = 0;
    remoteRootEntries = {};
    remoteRootOmitted = {};
    remoteOmittedCount = 0;
    remotePreviewEntries = [];
    remoteError = '';
    remoteNeedsSignIn = false;
    isRemoteLoading = false;
  }

  function clearRemoteNavigation(): void {
    cancelProjectSearch();
    folderSearchQuery = '';
    autoBrowsedProjectId = null;
    resetRootPrefetch();
    remoteRequestController?.abort();
    remoteRequestController = null;
    remoteRequestGeneration += 1;
    activeRemoteFullscreen = null;
    activeRemoteGenericFile = null;
    activeRemoteSourceId = null;
    remotePath = '.';
    remoteEntries = [];
    remotePageIndex = 0;
    remotePageCursors = [null];
    remoteNextCursor = null;
    remoteLegacyEntries = null;
    storedPageIndex = 0;
    remoteRootEntries = {};
    remoteRootOmitted = {};
    remoteOmittedCount = 0;
    remotePreviewEntries = [];
    remoteError = '';
    remoteNeedsSignIn = false;
    isRemoteLoading = false;
  }

  function resetRootPrefetch(): void {
    rootPrefetchController?.abort();
    rootPrefetchController = null;
    rootPrefetchEpoch += 1;
    rootPrefetchInFlight = false;
    rootPrefetchCount = 0;
    rootPrefetchKeys.clear();
    remoteRootPreviewStatus = {};
    rootPrefetchVersion += 1;
  }

  function beginRemoteRequest(): { controller: AbortController; generation: number; projectId: string | null } {
    remoteRequestController?.abort();
    remoteNeedsSignIn = false;
    const controller = new AbortController();
    remoteRequestController = controller;
    remoteRequestGeneration += 1;
    return {
      controller,
      generation: remoteRequestGeneration,
      projectId: selectedProject?.project_id ?? null,
    };
  }

  function isCurrentRemoteRequest(request: { generation: number; projectId: string | null }, sourceId: string): boolean {
    return request.generation === remoteRequestGeneration
      && request.projectId === selectedProject?.project_id
      && sourceId === activeRemoteSourceId;
  }

  function finishRemoteRequest(request: { controller: AbortController; generation: number }): void {
    if (request.generation !== remoteRequestGeneration) return;
    if (remoteRequestController === request.controller) remoteRequestController = null;
    isRemoteLoading = false;
  }

  function remoteRequestError(error: unknown, fallback: string): string | null {
    if (error instanceof DOMException && error.name === 'AbortError') return null;
    remoteNeedsSignIn = error instanceof ProjectRemoteAccessError
      && error.code === 'requester_device_identity_unavailable';
    if (remoteNeedsSignIn) return $text('projects.source_session_reconnect');
    return error instanceof Error ? error.message : fallback;
  }

  async function signOutToReconnectSource(): Promise<void> {
    const returnUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    await authStore.logout({
      // Standard logout clears the hash; restore this Project route before login.
      afterLocalLogout: () => replaceState(returnUrl, {}),
      afterServerCleanup: () => window.dispatchEvent(new Event('openLoginInterface')),
    });
  }

  async function refreshRemoteSourceStatus(): Promise<void> {
    const project = selectedProject;
    if (!project) return;
    try {
      const refreshed = await listProjectSources(project);
      if (selectedProject?.project_id !== project.project_id) return;
      const disconnectedSourceIds = new Set(sources.filter((source) => source.status === 'connected'
        && !refreshed.some((candidate) => candidate.source_id === source.source_id && candidate.status === 'connected'))
        .map((source) => source.source_id));
      sources = refreshed;
      if (disconnectedSourceIds.size > 0) {
        if (remoteDownloadProgress && disconnectedSourceIds.has(remoteDownloadProgress.sourceId)) cancelRemoteDownload();
        const retainedUrls: Record<string, string> = {};
        for (const [key, url] of Object.entries(remoteImageUrls)) {
          if ([...disconnectedSourceIds].some((sourceId) => key.startsWith(`${sourceId}:`))) URL.revokeObjectURL(url);
          else retainedUrls[key] = url;
        }
        remoteImageUrls = retainedUrls;
        if (activeRemoteImage && disconnectedSourceIds.has(activeRemoteImage.sourceId)) activeRemoteImage = null;
        remoteRootEntries = Object.fromEntries(Object.entries(remoteRootEntries)
          .filter(([sourceId]) => !disconnectedSourceIds.has(sourceId)));
        remoteRootOmitted = Object.fromEntries(Object.entries(remoteRootOmitted)
          .filter(([sourceId]) => !disconnectedSourceIds.has(sourceId)));
      }
      const active = refreshed.find((source) => source.source_id === activeRemoteSourceId);
      if (activeRemoteSourceId && (!active || active.status !== 'connected')) {
        autoBrowsedProjectId = null;
        remoteRequestController?.abort();
        remoteRequestController = null;
        remoteRequestGeneration += 1;
        activeRemoteFullscreen = null;
        activeRemoteGenericFile = null;
        activeRemoteImage = null;
        remoteEntries = [];
        remoteRootEntries = {};
        remoteRootOmitted = {};
        remotePreviewEntries = [];
        remoteOmittedCount = 0;
        isRemoteLoading = false;
        remoteError = active ? 'This Project source is offline' : 'This Project source is no longer available';
        remoteNeedsSignIn = false;
        activeRemoteSourceId = null;
      }
    } catch (error) {
      console.error('[ProjectsPage] Failed to refresh remote source status:', error);
    }
  }

  async function prefetchRemoteRoots(
    project: ProjectViewModel,
    ownerId: string | null | undefined,
    candidates: ProjectSourceViewModel[],
  ): Promise<void> {
    if (!previewState?.remoteEntries && !previewState?.legacyRemoteEntries && !ownerId) return;
    rootPrefetchInFlight = true;
    const epoch = rootPrefetchEpoch;
    const controller = new AbortController();
    rootPrefetchController = controller;
    remoteRootPreviewStatus = { ...remoteRootPreviewStatus,
      ...Object.fromEntries(candidates.map((source) => [source.source_id, 'loading' as const])) };
    try {
      for (let offset = 0; offset < candidates.length; offset += 2) {
        if (controller.signal.aborted) return;
        await Promise.all(candidates.slice(offset, offset + 2).map(async (source) => {
          try {
            const previewEntries = previewState?.remoteEntries ?? previewState?.legacyRemoteEntries;
            const result = previewEntries
              ? { entries: previewEntries.slice(0, 12), omitted: Math.max(0, previewEntries.length - 12) }
              : await requestProjectRemoteAccess<ProjectRemoteDirectoryResult>(
                project, source, { ownerId: ownerId ?? '', teamId: getActiveTeamContextSnapshot().teamId },
                'list', { path: '.', maxEntries: 12 }, controller.signal,
              );
            if (controller.signal.aborted || epoch !== rootPrefetchEpoch || selectedProject?.project_id !== project.project_id
              || !sources.some((candidate) => candidate.source_id === source.source_id && candidate.status === 'connected')) return;
            remoteRootEntries = { ...remoteRootEntries, [source.source_id]: result.entries };
            remoteRootOmitted = { ...remoteRootOmitted, [source.source_id]: result.omitted };
            const status = { ...remoteRootPreviewStatus };
            delete status[source.source_id];
            remoteRootPreviewStatus = status;
          } catch (error) {
            if (controller.signal.aborted || epoch !== rootPrefetchEpoch) return;
            remoteRootPreviewStatus = { ...remoteRootPreviewStatus, [source.source_id]: 'unavailable' };
            console.warn('[ProjectsPage] Could not load connected source folder summary:', error);
          }
        }));
      }
    } finally {
      if (rootPrefetchController === controller) rootPrefetchController = null;
      if (epoch === rootPrefetchEpoch) {
        rootPrefetchInFlight = false;
        rootPrefetchVersion += 1;
      }
    }
  }

  async function browseRemoteSource(source: ProjectSourceViewModel, path = '.', pageIndex = 0): Promise<void> {
    if (!selectedProject) return;
    cancelProjectSearch();
    folderSearchQuery = '';
    const cursor = path === remotePath && source.source_id === activeRemoteSourceId
      ? remotePageCursors[pageIndex] ?? null : null;
    currentFolder = null;
    currentFolderTrail = [];
    currentFolderHash = null;
    currentVirtualPath = null;
    activeRemoteSourceId = source.source_id;
    activeRemoteFullscreen = null;
    activeRemoteGenericFile = null;
    remotePreviewEntries = [];
    const legacy = remoteLegacyEntries;
    if (legacy?.sourceId === source.source_id && legacy.path === path) {
      const start = pageIndex * FILES_PAGE_SIZE;
      remotePath = path;
      remoteEntries = legacy.entries.slice(start, start + FILES_PAGE_SIZE);
      remotePageIndex = pageIndex;
      remoteNextCursor = start + FILES_PAGE_SIZE < legacy.entries.length
        ? remoteEntries.at(-1)?.path.split('/').at(-1) ?? null : null;
      remoteOmittedCount = legacy.omitted + Math.max(0, legacy.entries.length - start - remoteEntries.length);
      remoteError = '';
      return;
    }
    remoteLegacyEntries = null;
    if (previewState?.remoteEntries) {
      const sorted = previewState.remoteEntries.filter((entry) => directParentPath(entry.path) === path)
        .sort((left, right) => left.path.localeCompare(right.path));
      const start = pageIndex * FILES_PAGE_SIZE;
      remotePath = path;
      remoteEntries = sorted.slice(start, start + FILES_PAGE_SIZE);
      remotePageIndex = pageIndex;
      remoteNextCursor = sorted[start + FILES_PAGE_SIZE - 1]?.path.split('/').at(-1) ?? null;
      if (start + FILES_PAGE_SIZE >= sorted.length) remoteNextCursor = null;
      remotePageCursors = [...remotePageCursors.slice(0, pageIndex + 1), remoteNextCursor];
      if (path === '.' && pageIndex === 0) {
        remoteRootEntries = { ...remoteRootEntries, [source.source_id]: remoteEntries };
        remoteRootOmitted = { ...remoteRootOmitted, [source.source_id]: sorted.length - remoteEntries.length };
      }
      remoteOmittedCount = Math.max(0, sorted.length - start - remoteEntries.length);
      remoteError = '';
      return;
    }
    if (previewState?.legacyRemoteEntries) {
      const result = { entries: previewState.legacyRemoteEntries, omitted: 0 };
      remoteLegacyEntries = { sourceId: source.source_id, path, ...result };
      remotePath = path;
      remoteEntries = result.entries.slice(0, FILES_PAGE_SIZE);
      remotePageIndex = 0;
      remoteNextCursor = remoteEntries.at(-1)?.path.split('/').at(-1) ?? null;
      remoteOmittedCount = result.entries.length - remoteEntries.length;
      remoteError = '';
      return;
    }
    if (!$userProfile.user_id) return;
    const request = beginRemoteRequest();
    isRemoteLoading = true;
    remoteError = '';
    try {
      const result = await requestProjectRemoteAccess<ProjectRemoteDirectoryResult>(
        selectedProject,
        source,
        { ownerId: $userProfile.user_id, teamId: getActiveTeamContextSnapshot().teamId },
        'list',
        { path, maxEntries: FILES_PAGE_SIZE, ...(cursor ? { cursor } : {}) },
        request.controller.signal,
      );
      if (!isCurrentRemoteRequest(request, source.source_id)) return;
      remotePath = path;
      if (result.entries.length > FILES_PAGE_SIZE && !result.nextCursor) {
        // Older connected CLIs ignore cursor/maxEntries. Page their returned
        // entries in memory so a legacy response never mounts hundreds of cards.
        remoteLegacyEntries = { sourceId: source.source_id, path, entries: result.entries, omitted: result.omitted };
      }
      remoteEntries = result.entries.slice(0, FILES_PAGE_SIZE);
      remotePageIndex = pageIndex;
      remoteNextCursor = remoteLegacyEntries
        ? remoteEntries.at(-1)?.path.split('/').at(-1) ?? null : result.nextCursor ?? null;
      remotePageCursors = [...(pageIndex === 0 ? [null] : remotePageCursors.slice(0, pageIndex + 1)), remoteNextCursor];
      if (path === '.' && pageIndex === 0) {
        remoteRootEntries = { ...remoteRootEntries, [source.source_id]: remoteEntries };
        remoteRootOmitted = { ...remoteRootOmitted, [source.source_id]: result.omitted + result.entries.length - remoteEntries.length };
      }
      remoteOmittedCount = result.omitted + result.entries.length - remoteEntries.length;
    } catch (error) {
      const message = remoteRequestError(error, 'Could not browse this source');
      if (!message || !isCurrentRemoteRequest(request, source.source_id)) return;
      remoteError = message;
      console.error('[ProjectsPage] Failed to browse remote source:', error);
    } finally {
      finishRemoteRequest(request);
    }
  }

  async function openRemoteEntry(source: ProjectSourceViewModel, entry: ProjectRemoteDirectoryEntry): Promise<void> {
    if (entry.kind === 'directory') {
      await browseRemoteSource(source, entry.path);
      return;
    }
    await openRemoteFile(source, entry.path);
  }

  async function openRemoteFile(source: ProjectSourceViewModel, path: string): Promise<void> {
    if (!selectedProject) return;
    const classification = classifyRemotePreviewPath(path);
    if (classification.kind === 'unsupported') {
      const listed = remoteEntries.find((candidate) => candidate.path === path);
      openRemoteGenericFile(source, path, listed?.sizeBytes);
      return;
    }
    activeRemoteSourceId = source.source_id;
    if (previewState?.remoteEntries) {
      const content = path.endsWith('.md')
        ? '# Connected project file\n\nThis preview is loaded from the connected source.'
        : 'export const connectedProjectFile = true;';
      const preview = normalizeRemoteFilePreview({
        sourceId: source.source_id,
        path,
        displayName: path.split('/').filter(Boolean).pop() || path,
        language: classification.language,
        snippet: content,
        sizeBytes: new TextEncoder().encode(content).byteLength,
        lineCount: content.split('\n').length,
        previewPolicy: 'component_preview',
      });
      remotePreviewEntries = [{ preview, readResult: null, canImport: false, sourceLabel: source.displayName || source.source_id }];
      activeRemoteFullscreen = remoteFullscreenDetail(preview, content, source.displayName || source.source_id);
      return;
    }
    if (!$userProfile.user_id) return;
    const request = beginRemoteRequest();
    isRemoteLoading = true;
    remoteError = '';
    try {
      const result = await requestProjectRemoteAccess<ProjectRemoteTextResult>(
        selectedProject,
        source,
        { ownerId: $userProfile.user_id, teamId: getActiveTeamContextSnapshot().teamId },
        'read_text',
        { path },
        request.controller.signal,
      );
      if (!isCurrentRemoteRequest(request, source.source_id)) return;
      const preview = normalizeRemoteFilePreview({
        sourceId: source.source_id,
        path,
        displayName: path.split('/').filter(Boolean).pop() || path,
        language: classification.language,
        snippet: result.content.slice(0, 20_000),
        snippetTruncated: result.content.length > 20_000 || result.truncated,
        baseHash: result.expectedBase ?? undefined,
        sizeBytes: result.sizeBytes,
        lineCount: result.lineCount,
        previewPolicy: result.truncated ? 'bounded_truncated_text' : 'bounded_full_text',
        safetyFlags: result.truncated ? ['truncated'] : [],
      });
      const entry = {
        preview,
        readResult: result.truncated ? null : result,
        canImport: !result.truncated && /^[a-f0-9]{64}$/i.test(result.expectedBase ?? ''),
        sourceLabel: source.displayName || source.source_id,
      };
      remotePreviewEntries = [entry, ...remotePreviewEntries.filter((candidate) => candidate.preview.embed.embed_id !== preview.embed.embed_id)];
      activeRemoteFullscreen = remoteFullscreenDetail(preview, result.content, source.displayName || source.source_id);
    } catch (error) {
      if (error instanceof ProjectRemoteAccessError && error.code === 'unsupported_file'
        && isCurrentRemoteRequest(request, source.source_id)) {
        const listed = remoteEntries.find((candidate) => candidate.path === path);
        const preview = normalizeRemoteFilePreview({
          sourceId: source.source_id,
          path,
          displayName: path.split('/').filter(Boolean).pop() || path,
          language: classification.language,
          snippet: '',
          sizeBytes: listed?.sizeBytes,
          previewPolicy: 'unsupported_binary',
          safetyFlags: [],
        });
        remotePreviewEntries = [{ preview, readResult: null, canImport: false,
          sourceLabel: source.displayName || source.source_id },
          ...remotePreviewEntries.filter((candidate) => candidate.preview.embed.embed_id !== preview.embed.embed_id)];
        remoteError = '';
        openRemoteGenericFile(source, path, listed?.sizeBytes);
        return;
      }
      const message = remoteRequestError(error, 'Could not read this file');
      if (!message || !isCurrentRemoteRequest(request, source.source_id)) return;
      remoteError = message;
      console.error('[ProjectsPage] Failed to read remote file:', error);
    } finally {
      finishRemoteRequest(request);
    }
  }

  function remoteEntryPreview(source: ProjectSourceViewModel, entry: ProjectRemoteDirectoryEntry): RemotePreviewEntry {
    const loaded = remotePreviewEntries.find((candidate) => candidate.preview.embed.content.source_id === source.source_id
      && candidate.preview.embed.content.path === entry.path);
    if (loaded) return loaded;
    const classification = classifyRemotePreviewPath(entry.path);
    const isUnsupported = entry.previewable === false || classification.kind === 'unsupported';
    return {
      preview: normalizeRemoteFilePreview({
        sourceId: source.source_id,
        path: entry.path,
        displayName: entry.path.split('/').filter(Boolean).pop() || entry.path,
        language: classification.kind === 'unsupported' ? 'text' : classification.language,
        snippet: '',
        snippetTruncated: false,
        sizeBytes: entry.sizeBytes,
        previewPolicy: isUnsupported ? 'unsupported_binary' : 'bounded_full_text',
        safetyFlags: [],
      }),
      readResult: null,
      canImport: false,
      sourceLabel: source.displayName || source.source_id,
    };
  }

  async function openFolder(folder: ProjectFolderViewModel): Promise<void> {
    clearRemoteNavigation();
    storedPageIndex = 0;
    currentVirtualPath = null;
    currentFolder = folder;
    currentFolderHash = folderHashes.get(folder.folder_id) ?? await computeSHA256(folder.folder_id);
    const trail: ProjectFolderViewModel[] = [];
    let cursor: ProjectFolderViewModel | undefined = folder;
    const visited = new Set<string>();
    while (cursor && !visited.has(cursor.folder_id)) {
      visited.add(cursor.folder_id);
      trail.unshift(cursor);
      const parentHash: string | null = cursor.parentHash;
      cursor = parentHash
        ? folders.find((candidate) => folderHashes.get(candidate.folder_id) === parentHash)
        : undefined;
    }
    currentFolderTrail = trail;
  }

  function openVirtualFolder(folder: ProjectVirtualFolder): void {
    clearRemoteNavigation();
    storedPageIndex = 0;
    currentFolder = null;
    currentFolderTrail = [];
    currentFolderHash = null;
    currentVirtualPath = folder.path;
  }

  function openRoot(): void {
    clearRemoteNavigation();
    storedPageIndex = 0;
    // A deliberate breadcrumb return must stay at the project root instead of
    // immediately triggering the connected-source auto-open effect again.
    autoBrowsedProjectId = selectedProject?.project_id ?? null;
    currentFolder = null;
    currentFolderTrail = [];
    currentFolderHash = null;
    currentVirtualPath = null;
  }

  async function loadProjectEmbed(item: ProjectItemViewModel): Promise<{
    embedData: Record<string, unknown>;
    decodedContent: Record<string, unknown>;
  } | null> {
    const previewEmbed = previewState?.embeds?.[item.target_id];
    if (previewEmbed) return previewEmbed;
    const project = selectedProject;
    if (!project || item.item_type !== 'embed') return null;
    try {
      const head = await readEncryptedProjectFile(project, item.target_id, {
        teamId: getActiveTeamContextSnapshot().teamId,
      });
      if (selectedProject?.project_id !== project.project_id) return null;
      const type = String(head.content.type || item.metadata.embed_type || 'code');
      return {
        embedData: {
          embed_id: item.target_id,
          type,
          status: 'finished',
          content: JSON.stringify(head.content),
          version_number: head.revision,
        },
        decodedContent: head.content,
      };
    } catch {
      // Older linked embeds may only have a chat/master wrapper. The card's
      // generic resolver remains the compatibility fallback.
      return null;
    }
  }

  function handleStartProjectInspiration(inspiration: ProjectInspiration): void {
    newProjectName = inspiration.phrase || inspiration.title || '';
  }

  function showProjectVoiceInputUnavailable(): void {
    notificationStore.info('Voice input for projects is coming soon.', 4000, true, 'projects-voice-input');
  }

  function openSelectedProjectSettings(): void {
    if (!selectedProject) return;
    panelState.openSettings();
    settingsDeepLink.set(`projects/${selectedProject.project_id}`);
  }

  function currentCreationTarget(): ProjectCreationTarget | null {
    if (!selectedProject) return null;
    const localFolderPath = currentFolderTrail.length > 0
      ? currentFolderTrail.map((folder) => folder.name || 'Untitled folder').join('/')
      : null;
    const isRemoteTarget = Boolean(activeRemoteSourceId && !currentFolder && currentVirtualPath === null);
    const remoteFolderPath = isRemoteTarget && remotePath !== '.' ? remotePath.replace(/^\.\//, '').replace(/\/$/, '') : null;
    return {
      projectId: selectedProject.project_id,
      projectName: selectedProject.name || 'Untitled project',
      folderId: currentFolder?.folder_id ?? null,
      folderPath: currentFolder ? localFolderPath : (remoteFolderPath ?? currentVirtualPath),
      sourceId: isRemoteTarget ? activeRemoteSourceId : null,
      teamId: getActiveTeamContextSnapshot().teamId,
    };
  }

  function startProjectChat(): void {
    const target = currentCreationTarget();
    if (!target) return;
    showCreateMenu = false;
    onNewChat(target);
  }

  function startProjectWorkflow(): void {
    const target = currentCreationTarget();
    if (!target) return;
    showCreateMenu = false;
    onNewWorkflow(target);
  }

  function startProjectPlan(): void {
    const target = currentCreationTarget();
    if (!target) return;
    showCreateMenu = false;
    onNewPlan(target);
  }

  onMount(() => {
    // Recover temporary browser files left by a closed or crashed download tab.
    void cleanupStaleConnectedProjectDownloads().catch(() => {});
    if (previewState) {
      projects = [previewState.project];
      selectedProject = previewState.startAtHome ? null : previewState.project;
      folders = previewState.folders ?? [];
      items = previewState.items ?? [];
      sources = previewState.sources ?? [];
      replaceReadmeState(previewState.readme ?? { status: 'empty' });
      activeTab = initialTab;
      isLoading = false;
      return () => { pageDisposed = true; cancelProjectSearch(); replaceReadmeState({ status: 'empty' }); };
    }
    syncProjectHashFromLocation();
    void refreshProjects();
    const handleProjectSelected = (event: Event) => {
      const project = (event as CustomEvent<ProjectViewModel>).detail;
      if (!project || selectedProject?.project_id === project.project_id) return;
      selectedProject = project;
      currentFolder = null;
      currentFolderTrail = [];
      currentFolderHash = null;
      currentVirtualPath = null;
      if (variant === 'main') setProjectUrlState(project.project_id);
      void refreshSelectedProject();
    };
    const handleProjectsChanged = (event: Event) => {
      void refreshProjects();
      const projectId = (event as CustomEvent<{ projectId?: string }>).detail?.projectId;
      if (selectedProject && (!projectId || projectId === selectedProject.project_id)) {
        void refreshSelectedProject();
      }
    };
    const sourceStatusTimer = window.setInterval(() => void refreshRemoteSourceStatus(), 15_000);
    window.addEventListener('hashchange', syncProjectHashFromLocation);
    window.addEventListener('popstate', syncProjectHashFromLocation);
    window.addEventListener(PROJECT_SELECTED_EVENT, handleProjectSelected);
    window.addEventListener(PROJECTS_CHANGED_EVENT, handleProjectsChanged);
    return () => {
      pageDisposed = true;
      cancelProjectSearch();
      replaceReadmeState({ status: 'empty' });
      cancelRemoteDownload();
      remoteRequestController?.abort();
      rootPrefetchController?.abort();
      for (const url of Object.values(remoteImageUrls)) URL.revokeObjectURL(url);
      window.removeEventListener('hashchange', syncProjectHashFromLocation);
      window.removeEventListener('popstate', syncProjectHashFromLocation);
      window.removeEventListener(PROJECT_SELECTED_EVENT, handleProjectSelected);
      window.removeEventListener(PROJECTS_CHANGED_EVENT, handleProjectsChanged);
      window.clearInterval(sourceStatusTimer);
    };
  });

  $effect(() => {
    if (previewState || variant !== 'main' || isLoading) return;
    if (!projectHashId) {
      if (selectedProject) clearSelectedProject();
      return;
    }
    if (selectedProject?.project_id === projectHashId) return;
    void selectProjectById(projectHashId, false);
  });
</script>

{#snippet projectSearchCard(entry: ProjectFileSearchEntry)}
  {#if entry.kind === 'remote'}
    {@const source = sources.find((candidate) => candidate.source_id === entry.sourceId)}
    {@const listedFolder = remoteEntries.find((candidate) => candidate.path === entry.path && candidate.kind === 'directory')}
    {#if source}
      {#if viewMode === 'list'}
        <button class="remote-list-entry" data-testid="project-search-result" type="button" onclick={() => void openRemoteEntry(source, { path: entry.path, kind: entry.entryKind })}>
          <span class="remote-list-icon" class:folder-list-icon={entry.entryKind === 'directory'} class:file-icon={entry.entryKind === 'file'} aria-hidden="true"></span>
          <strong>{searchResultName(entry)}</strong>
          <small>{source.displayName || source.source_id} / {entry.path}</small>
        </button>
      {:else if entry.entryKind === 'directory'}
        <div class="folder-preview remote-preview-badged search-result-card" data-testid="project-search-result">
          <span class="remote-cloud-badge" role="img" aria-label="Stored remotely"></span>
          <UnifiedEmbedPreview id={`${entry.sourceId}:${entry.path}`} presentationOnly appId="files" skillId="file"
            skillIconName="files" appIconName="files" status="finished" showSkillIcon={false}
            skillName={searchResultName(entry)} customStatusText={listedFolder ? remoteFolderStatus(listedFolder) : 'Folder'}
            onFullscreen={() => void browseRemoteSource(source, entry.path)}>
            {#snippet details()}
              <span class="folder-card-contents">
                {#each listedFolder?.children?.slice(0, 3) ?? [] as child (child.path)}
                  <span class="folder-child-row"><span class:child-folder={child.kind === 'directory'} class="folder-child-icon" aria-hidden="true"></span><span>{child.path.split('/').at(-1) || child.path}</span></span>
                {:else}
                  <span class="folder-empty-row">Open to view contents</span>
                {/each}
              </span>
            {/snippet}
          </UnifiedEmbedPreview>
          <small class="search-result-location">{source.displayName || source.source_id} / {entry.path}</small>
        </div>
      {:else}
        {@const preview = normalizeRemoteFilePreview({ sourceId: entry.sourceId, path: entry.path,
          displayName: searchResultName(entry), language: classifyRemotePreviewPath(entry.path).language,
          snippet: '', previewPolicy: 'metadata_only', safetyFlags: [] })}
        <div class="search-result-card" data-testid="project-search-result">
          <ProjectRemotePreviewCard {preview} sourceLabel={source.displayName || source.source_id}
            onOpenFullscreen={() => void openRemoteFile(source, entry.path)}
            onOpenFile={() => void openRemoteFileDetails(source, entry.path)} />
          <small class="search-result-location">{source.displayName || source.source_id} / {entry.path}</small>
        </div>
      {/if}
    {/if}
  {:else if entry.kind === 'item'}
    <div class="search-result-card" data-testid="project-search-result">
      <ProjectBrowserItem item={entry.item} {viewMode} displayName={projectBrowserItemName(entry.item)}
        loadProjectEmbed={loadProjectEmbed} onOpenFullscreen={openStoredFullscreen} />
    </div>
  {:else}
    <div class="folder-preview search-result-card" data-testid="project-search-result">
      <UnifiedEmbedPreview id={entry.kind === 'folder' ? entry.folder.folder_id : entry.folder.path}
        presentationOnly appId="files" skillId="file" skillIconName="files" appIconName="files"
        status="finished" showSkillIcon={false} skillName={searchResultName(entry)}
        customStatusText="Folder"
        onFullscreen={entry.kind === 'folder' ? () => void openFolder(entry.folder) : () => openVirtualFolder(entry.folder)}>
        {#snippet details()}
          <span class="folder-card-contents"><span class="folder-empty-row">Open to view contents</span></span>
        {/snippet}
      </UnifiedEmbedPreview>
    </div>
  {/if}
{/snippet}

{#snippet createProjectForm(compact = false)}
  <form class="create-row" class:compact onsubmit={(event) => { event.preventDefault(); requestProjectCreation(); }}>
    <input
      data-testid="project-name-input"
      bind:value={newProjectName}
      placeholder="New project name"
      aria-label="New project name"
    />
    <button data-testid="project-create-button" type="submit" disabled={isSaving || !newProjectName.trim()}>
      Create project
    </button>
  </form>
{/snippet}

{#snippet writePolicyChoice()}
  <fieldset class="write-policy-choice" data-testid="project-write-policy-choice">
    <legend>{$text('settings.projects.write_policy_prompt')}</legend>
    <label>
      <input data-testid="project-write-policy-apply-and-show" type="radio" name="project-write-policy" value="apply_and_show" bind:group={newProjectWriteMode} />
      <span><strong>{$text('settings.projects.write_mode_apply_and_show')}</strong><small>{$text('settings.projects.write_mode_apply_and_show_description')}</small></span>
    </label>
    <label>
      <input data-testid="project-write-policy-always-ask" type="radio" name="project-write-policy" value="always_ask" bind:group={newProjectWriteMode} />
      <span><strong>{$text('settings.projects.write_mode_always_ask')}</strong><small>{$text('settings.projects.write_mode_always_ask_description')}</small></span>
    </label>
  </fieldset>
{/snippet}

{#snippet projectList(showEmpty = true)}
  {#if isLoading}
    <p class="muted">Loading projects...</p>
  {:else if hasLoadError}
    <div class="load-error" data-testid="projects-load-error">
      <p>Failed to load projects.</p>
      <button type="button" onclick={() => void refreshProjects()}>Retry</button>
    </div>
  {:else if sortedProjects.length === 0 && showEmpty}
    <p class="muted">No projects yet. Create one to start organizing saved work.</p>
  {:else}
    <div class="project-list" data-testid="project-list">
      {#each sortedProjects as project (project.project_id)}
        <article
          class:active={selectedProject?.project_id === project.project_id}
          class="project-card"
          data-testid="project-card"
        >
          <button type="button" onclick={() => void selectProject(project)}>
            <span class="sidebar-project-icon" aria-hidden="true">{project.icon || 'folder'}</span>
            <span class="sidebar-project-copy">
              <strong>{project.name || 'Untitled project'}</strong>
              <small>{project.encrypted.item_count ?? 0} items</small>
            </span>
          </button>
          <a href={projectStateHref(project.project_id)} aria-label={`Open ${project.name || 'Untitled project'}`} data-testid="project-detail-link" onclick={(event) => { event.preventDefault(); void selectProject(project); }}>›</a>
        </article>
      {/each}
    </div>
  {/if}
{/snippet}

{#snippet selectedProjectDetails()}
  {#if selectedProject}
      <ProjectWorkspaceHeader
        title={selectedProject.name || 'Untitled project'}
        description={selectedProject.description || 'Add chats, embeds, PDFs, sheets, images, audio, video, code, mail, and files.'}
        icon={selectedProject.icon || 'folder'}
        startedAt={selectedProject.encrypted.created_at}
        onSaveTitle={saveSelectedProjectTitle}
        onSaveDescription={saveSelectedProjectDescription}
        onSettings={openSelectedProjectSettings}
        onDelete={() => void handleDeleteProject(selectedProject as ProjectViewModel)}
        onClose={openProjectsHome}
      />
      <input bind:this={uploadInput} type="file" onchange={handleUploadSelected} hidden />

      <div class="project-tabs" data-testid="project-tabs">
        <SettingsTabs
          tabs={projectTabs}
          bind:activeTab
          maxVisibleTabs={3}
          testIdPrefix="project-tab"
        />
      </div>

      {#if activeTab === 'overview'}
        <section class="project-panel overview-panel" role="tabpanel" id="tabpanel-overview" data-testid="project-overview-panel">
          <ProjectReadme
            state={readmeState}
            onUpload={() => uploadInput?.click()}
            onCreate={() => (showCreateMenu = !showCreateMenu)}
            onRetry={() => void retryProjectReadme()}
          />
          {#if showCreateMenu}
            <div class="create-menu" data-testid="project-create-menu">
              <button type="button" data-testid="project-create-chat" onclick={startProjectChat}>
                <span class="menu-icon chat-icon" aria-hidden="true"></span>
                <span><strong>New chat</strong><small>Start a chat inside this project</small></span>
              </button>
              <button type="button" data-testid="project-create-workflow" onclick={startProjectWorkflow}>
                <span class="menu-icon workflow-icon" aria-hidden="true"></span>
                <span><strong>New workflow</strong><small>Build a workflow for this project</small></span>
              </button>
              <button type="button" data-testid="project-create-plan" onclick={startProjectPlan}>
                <span class="menu-icon plan-icon" aria-hidden="true"></span>
                <span><strong>New plan</strong><small>Plan work for this project</small></span>
              </button>
            </div>
          {/if}
          {#if readmeState.status === 'empty'}
            <div class="legacy-empty-contract" data-testid="project-empty-items" aria-hidden="true"></div>
          {/if}
        </section>
      {:else if activeTab === 'folders'}
      <section class="project-panel folders-panel" class:viewer-split-open={viewerSplitOpen} role="tabpanel" id="tabpanel-folders" data-testid="project-folders-panel">
        <div class="folder-summary-row">
          <strong>{projectSearchActive ? `${orderedSearchResults.length} search results` : activeRemoteSource ? `${remoteEntryCount} files and folders` : `${browserFolders.length + browserVirtualFolders.length} folders, ${browserItems.length} files and embeds`}</strong>
          <label class="folder-search">
            <span class="search-icon" aria-hidden="true"></span>
            <span class="sr-only">Search project files</span>
            <input bind:value={folderSearchQuery} type="search" placeholder="Search" data-testid="project-folder-search" oninput={handleFolderSearchInput} onkeydown={(event) => { if (event.key === 'Enter') { event.preventDefault(); void searchProjectFiles(); } }} />
          </label>
          <button class="sort-button" type="button" data-testid="project-folder-sort" disabled={!!activeRemoteSource || projectSearchActive} aria-label={activeRemoteSource ? 'Files sorted by name' : sortNewestFirst ? 'Show oldest first' : 'Show most recent first'} onclick={() => (sortNewestFirst = !sortNewestFirst)}>
            <span>{activeRemoteSource || projectSearchActive ? 'Name A–Z' : sortNewestFirst ? 'Most recent first' : 'Oldest first'}</span>
            <span class="sort-icon" aria-hidden="true"></span>
          </button>
        </div>

      <section class="project-section">
        {#if currentFolder || currentVirtualPath !== null || activeRemoteSource}
          {#if !activeRemoteSource || remotePathParts.length > 0}
          <div class="section-title">
            <div>
              <h3>{activeRemoteSource ? remotePathParts.at(-1) : currentVirtualPath?.split('/').at(-1) || currentFolder?.name || 'Untitled folder'}</h3>
            <nav class="project-breadcrumbs" aria-label="Project folder path">
              <button class="breadcrumb-button" type="button" onclick={openRoot}>{$text('projects.project_root')}</button>
              {#each currentFolderTrail as folder, index (folder.folder_id)}
                <span class="breadcrumb-separator">/</span>
                {#if index === currentFolderTrail.length - 1}
                  <span class="breadcrumb-current" aria-current="page">{folder.name || 'Untitled folder'}</span>
                {:else}
                  <button class="breadcrumb-button" type="button" onclick={() => void openFolder(folder)}>{folder.name || 'Untitled folder'}</button>
                {/if}
              {/each}
              {#each virtualFolderTrail as folder, index (folder.path)}
                <span class="breadcrumb-separator">/</span>
                {#if index === virtualFolderTrail.length - 1}
                  <span class="breadcrumb-current" aria-current="page">{folder.name}</span>
                {:else}
                  <button class="breadcrumb-button" type="button" onclick={() => openVirtualFolder(folder)}>{folder.name}</button>
                {/if}
              {/each}
              {#if activeRemoteSource}
                <span class="breadcrumb-separator">/</span>
                <button class="breadcrumb-button" type="button" onclick={() => void browseRemoteSource(activeRemoteSource, '.')}>{activeRemoteSource.displayName || 'Source root'}</button>
                {#each remotePathParts as part, index}
                  <span class="breadcrumb-separator">/</span>
                  {#if index === remotePathParts.length - 1}
                    <span class="breadcrumb-current" aria-current="page">{part}</span>
                  {:else}
                    <button class="breadcrumb-button" type="button" onclick={() => void browseRemoteSource(activeRemoteSource, remotePathParts.slice(0, index + 1).join('/'))}>{part}</button>
                  {/if}
                {/each}
              {/if}
              </nav>
            </div>
          </div>
          {/if}
        {/if}

          <div class="browser-toolbar">
            <span class="muted">{projectSearchActive ? `${orderedSearchResults.length} matches` : activeRemoteSource ? `${remotePageIndex * FILES_PAGE_SIZE + (remoteEntries.length ? 1 : 0)}–${remotePageIndex * FILES_PAGE_SIZE + remoteEntries.length} of ${remoteEntryCount} entries` : `${storedEntryCount} entries`}</span>
            <div class="view-toggle" aria-label="Project view mode">
              <button type="button" class:active={viewMode === 'tile'} onclick={() => (viewMode = 'tile')}>Tile</button>
              <button type="button" class:active={viewMode === 'list'} onclick={() => (viewMode = 'list')}>List</button>
            </div>
          </div>

        <div class:browser-grid={viewMode === 'tile'} class:browser-list={viewMode === 'list'} data-testid="project-browser-list">
            <div class="project-action-expander" class:expanded={showCreateMenu} data-testid="project-action-expander">
            <div class="project-actions" data-testid="project-folder-actions">
              <button type="button" onclick={() => void refreshSelectedProject()} disabled={isSaving}>
                <span class="tray-icon sync-icon" aria-hidden="true"></span><span>Sync</span>
              </button>
              <button type="button" onclick={() => uploadInput?.click()} disabled={isSaving} data-testid="project-upload-button">
                <span class="tray-icon upload-icon" aria-hidden="true"></span><span>Upload</span>
              </button>
              <button type="button" onclick={() => (showCreateMenu = !showCreateMenu)} aria-expanded={showCreateMenu} aria-controls="project-folder-create-menu" data-testid="project-folder-create-menu-button">
                <span class="clickable-icon icon_create project-create-action-icon" aria-hidden="true"></span><span>Create</span>
              </button>
            </div>
            {#if showCreateMenu}
              <div class="create-menu folder-create-menu" id="project-folder-create-menu" data-testid="project-create-menu">
                <button type="button" data-testid="project-create-chat" onclick={startProjectChat}><span class="menu-icon chat-icon" aria-hidden="true"></span><span><strong>New chat</strong></span></button>
                <button type="button" data-testid="project-create-workflow" onclick={startProjectWorkflow}><span class="menu-icon workflow-icon" aria-hidden="true"></span><span><strong>New workflow</strong></span></button>
                <button type="button" data-testid="project-create-plan" onclick={startProjectPlan}><span class="menu-icon plan-icon" aria-hidden="true"></span><span><strong>New plan</strong></span></button>
              </div>
            {/if}
            </div>
            {#if projectSearchActive}
              <div class="project-search-results" data-testid="project-remote-search-results">
                {#if projectSearchLoading}
                  <p class="search-section-heading" data-testid="project-search-loading">Searching Project files and folders...</p>
                {/if}
                {#if projectSearchError}
                  <p class="remote-error search-section-heading">{projectSearchError}</p>
                  {#if remoteNeedsSignIn}
                    <button class="search-section-heading" type="button" data-testid="project-source-relogin" onclick={() => void signOutToReconnectSource()}>{$text('projects.source_session_relogin')}</button>
                  {/if}
                {/if}
                {#if searchPageIndex === 0 || searchPageCurrent.length > 0}
                  <h3 class="search-section-heading" data-testid="project-search-current-heading">{$text('projects.search_current_folder')}</h3>
                  {#each searchPageCurrent as result (searchResultKey(result))}
                    {@render projectSearchCard(result)}
                  {/each}
                  {#if searchPageIndex === 0 && searchPageCurrent.length === 0 && !projectSearchLoading}
                    <p class="search-section-heading muted">No matches in this folder.</p>
                  {/if}
                {/if}
                {#if searchPageAcross.length > 0 || searchPageIndex === 0}
                  <h3 class="search-section-heading" data-testid="project-search-across-heading">{$text('projects.search_across_project', { values: { project: selectedProject.name || 'Project' } })}</h3>
                  {#each searchPageAcross as result (searchResultKey(result))}
                    {@render projectSearchCard(result)}
                  {/each}
                  {#if searchPageIndex === 0 && searchPageAcross.length === 0 && !projectSearchLoading}
                    <p class="search-section-heading muted">No other matches in this Project.</p>
                  {/if}
                {/if}
                {#if projectSearchOmitted > 0}
                  <p class="remote-limit-notice search-section-heading" data-testid="project-remote-results-truncated">{$text('projects.remote_results_limited')}</p>
                {/if}
                {#if orderedSearchResults.length > FILES_PAGE_SIZE}
                  <nav class="files-page-controls" data-testid="project-search-page-controls" aria-label="Project search result pages">
                    <button type="button" disabled={searchPageIndex === 0} onclick={() => { searchPageIndex -= 1; void scrollToFilesStart(); }}>Previous</button>
                    <span>Page {searchPageIndex + 1} of {Math.ceil(orderedSearchResults.length / FILES_PAGE_SIZE)}</span>
                    <button type="button" disabled={(searchPageIndex + 1) * FILES_PAGE_SIZE >= orderedSearchResults.length} onclick={() => { searchPageIndex += 1; void scrollToFilesStart(); }}>Next</button>
                  </nav>
                {/if}
              </div>
            {:else}
            {#if visibleBrowserFolders.length === 0 && visibleVirtualFolders.length === 0 && visibleBrowserItems.length === 0 && visibleBrowserSources.length === 0 && !activeRemoteSource}
              <div class="empty-state" data-testid="project-empty-items">
                <h3>{normalizedFolderSearch ? 'No matching project items' : 'No project items yet'}</h3>
                <p>{normalizedFolderSearch ? 'Try a different search.' : 'Upload a file or use “Add to project” from chats and embed fullscreen views.'}</p>
              </div>
            {/if}
            {#each pageBrowserFolders as folder (folder.folder_id)}
              {@const cardEntries = folderCardEntries(folder)}
              {#if viewMode === 'tile'}
                <div class="folder-preview" data-testid="project-folder-card">
                  <UnifiedEmbedPreview
                    id={folder.folder_id}
                    presentationOnly
                    appId="files"
                    skillId="file"
                    skillIconName="files"
                    appIconName="files"
                    status="finished"
                    skillName={folder.name || 'Untitled folder'}
                    customStatusText={`${cardEntries.length} ${cardEntries.length === 1 ? 'file' : 'files'}`}
                    showSkillIcon={false}
                    onFullscreen={() => void openFolder(folder)}
                  >
                    {#snippet details()}
                      <span class="folder-card-contents">
                        {#each cardEntries.slice(0, 3) as entry (`${entry.kind}:${entry.name}`)}
                          <span class="folder-child-row" data-testid="project-folder-child"><span class:child-folder={entry.kind === 'folder'} class="folder-child-icon" aria-hidden="true"></span><span>{entry.name}</span><small>{entry.detail}</small></span>
                        {:else}
                          <span class="folder-empty-row">Empty folder</span>
                        {/each}
                        {#if cardEntries.length > 3}
                          <span class="folder-more-row">+ {cardEntries.length - 3} more files &amp; folders</span>
                        {/if}
                      </span>
                    {/snippet}
                  </UnifiedEmbedPreview>
                </div>
              {:else}
                <button class="folder-entry list" data-testid="project-folder-card" type="button" onclick={() => void openFolder(folder)}>
                  <span class="folder-icon">Folder</span>
                  <strong>{folder.name || 'Untitled folder'}</strong>
                  <small>{cardEntries.length} {cardEntries.length === 1 ? 'file' : 'files'}</small>
                </button>
              {/if}
            {/each}
            {#each pageVirtualFolders as folder (folder.path)}
              {#if viewMode === 'tile'}
                <div class="folder-preview remote-preview-badged" data-testid="project-virtual-folder-card">
                  <span class="remote-cloud-badge" data-testid="project-remote-cloud-badge" role="img" aria-label="Stored remotely" title="Stored remotely"></span>
                  <UnifiedEmbedPreview
                    id={folder.path}
                    presentationOnly
                    appId="files"
                    skillId="file"
                    skillIconName="files"
                    appIconName="files"
                    status="finished"
                    skillName={folder.name}
                    customStatusText="Hosted path"
                    showSkillIcon={false}
                    onFullscreen={() => openVirtualFolder(folder)}
                  >
                    {#snippet details()}
                      <span class="folder-card-contents">
                        <span class="folder-child-row"><span class="folder-child-icon child-folder" aria-hidden="true"></span><span>{folder.name}</span><small>Folder</small></span>
                      </span>
                    {/snippet}
                  </UnifiedEmbedPreview>
                </div>
              {:else}
                <button class="folder-entry list remote-preview-badged" data-testid="project-virtual-folder-card" type="button" onclick={() => openVirtualFolder(folder)}>
                  <span class="remote-cloud-badge" data-testid="project-remote-cloud-badge" role="img" aria-label="Stored remotely" title="Stored remotely"></span>
                  <span class="folder-icon">Folder</span>
                  <strong>{folder.name}</strong>
                  <small>Hosted path</small>
                </button>
              {/if}
            {/each}
            {#each pageBrowserItems as item (item.project_item_id)}
              <ProjectBrowserItem
                {item}
                {viewMode}
                displayName={projectBrowserItemName(item)}
                loadProjectEmbed={loadProjectEmbed}
                onOpenFullscreen={openStoredFullscreen}
              />
            {/each}
            {#each pageBrowserSources as source (source.source_id)}
              {#if viewMode === 'tile'}
                <div class="folder-preview remote-preview-badged" data-testid="project-connected-source-root" data-status={source.status}>
                  <span class="remote-cloud-badge" data-testid="project-remote-cloud-badge" role="img" aria-label="Stored remotely" title="Stored remotely"></span>
                  <UnifiedEmbedPreview
                    id={source.source_id}
                    presentationOnly
                    appId="files"
                    skillId="file"
                    skillIconName="files"
                    appIconName="files"
                    status={source.status === 'connected' ? 'finished' : 'failed'}
                    skillName={source.displayName || source.source_id}
                    customStatusText={source.status === 'connected' ? remoteRootStatus(source.source_id) : source.status.replaceAll('_', ' ')}
                    showSkillIcon={false}
                    onFullscreen={source.status === 'connected' ? () => void browseRemoteSource(source) : undefined}
                  >
                    {#snippet details()}
                      <span class="folder-card-contents">
                        {#each remoteRootChildren(source.source_id) as child (child.path)}
                          <span class="folder-child-row"><span class:child-folder={child.kind === 'directory'} class="folder-child-icon" aria-hidden="true"></span><span>{child.path.split('/').at(-1) || child.path}</span></span>
                        {:else}
                          <span class="folder-empty-row">{source.status === 'connected' ? remoteRootEntries[source.source_id] ? 'Empty folder' : remoteRootStatus(source.source_id) : source.status.replaceAll('_', ' ')}</span>
                        {/each}
                        {#if (remoteRootOmitted[source.source_id] ?? 0) > 0}
                          <span class="folder-more-row">More files &amp; folders</span>
                        {:else if (remoteRootEntries[source.source_id]?.length ?? 0) > 3}
                          <span class="folder-more-row">+ {(remoteRootEntries[source.source_id]?.length ?? 0) - 3} more files &amp; folders</span>
                        {/if}
                      </span>
                    {/snippet}
                  </UnifiedEmbedPreview>
                </div>
              {:else}
                <button
                  class="source-root-entry list remote-preview-badged"
                  data-testid="project-connected-source-root"
                  data-status={source.status}
                  type="button"
                  disabled={source.status !== 'connected'}
                  onclick={() => void browseRemoteSource(source)}
                >
                  <span class="remote-cloud-badge" data-testid="project-remote-cloud-badge" role="img" aria-label="Stored remotely" title="Stored remotely"></span>
                  <span class="source-root-icon">{$text('projects.connected_source')}</span>
                  <strong>{source.displayName || source.source_id}</strong>
                  <small>{source.status === 'connected' ? remoteRootStatus(source.source_id) : source.status.replaceAll('_', ' ')}</small>
                </button>
              {/if}
            {/each}
            {#if !activeRemoteSource && storedEntryCount > FILES_PAGE_SIZE}
              <nav class="files-page-controls" data-testid="project-files-page-controls" aria-label="Project file pages">
                <button type="button" disabled={storedPageIndex === 0} onclick={() => showStoredPage(storedPageIndex - 1)}>Previous</button>
                <span>Page {storedPageIndex + 1} of {Math.ceil(storedEntryCount / FILES_PAGE_SIZE)}</span>
                <button type="button" disabled={(storedPageIndex + 1) * FILES_PAGE_SIZE >= storedEntryCount} onclick={() => showStoredPage(storedPageIndex + 1)}>Next</button>
              </nav>
            {/if}
        {#if activeRemoteSource}
          <div class="remote-browser" data-testid="project-remote-browser">
            {#if remoteError}
              <p class="remote-error" data-testid="project-remote-error">{remoteError}</p>
              {#if remoteNeedsSignIn}
                <button type="button" data-testid="project-source-relogin" onclick={() => void signOutToReconnectSource()}>
                  {$text('projects.source_session_relogin')}
                </button>
              {/if}
            {/if}
            {#if remoteOmittedCount > 0 && !remoteNextCursor}
              <p class="remote-limit-notice" data-testid="project-remote-results-truncated">{$text('projects.remote_results_limited')}</p>
            {/if}
            {#if isRemoteLoading}
              <p class="muted" data-testid="project-remote-loading">Loading from your device...</p>
            {:else}
              <div class="remote-results" data-testid="project-remote-directory-results">
                {#each visibleRemoteEntries as entry (entry.path)}
                  {#if entry.kind === 'directory'}
                    {#if viewMode === 'list'}
                      <button class="remote-list-entry" data-testid="project-remote-entry" data-kind="directory" type="button" onclick={() => void openRemoteEntry(activeRemoteSource, entry)}>
                        <span class="remote-list-icon folder-list-icon" aria-hidden="true"></span>
                        <strong>{entry.path.split('/').at(-1) || entry.path}</strong>
                        <small>{remoteFolderStatus(entry)}</small>
                      </button>
                    {:else}
                    <div class="folder-preview remote-preview-badged" data-testid="project-remote-entry" data-kind="directory">
                      <span class="remote-cloud-badge" data-testid="project-remote-cloud-badge" role="img" aria-label="Stored remotely" title="Stored remotely"></span>
                      <UnifiedEmbedPreview
                        id={`${activeRemoteSource.source_id}:${entry.path}`}
                        presentationOnly
                        appId="files"
                        skillId="file"
                        skillIconName="files"
                        appIconName="files"
                        status="finished"
                        skillName={entry.path.split('/').filter(Boolean).pop() || entry.path}
                        customStatusText={remoteFolderStatus(entry)}
                        showSkillIcon={false}
                        onFullscreen={() => void openRemoteEntry(activeRemoteSource, entry)}
                      >
                        {#snippet details()}
                          <span class="folder-card-contents">
                            {#each entry.children ?? [] as child (child.path)}
                              <span class="folder-child-row" data-testid="project-remote-folder-child"><span class:child-folder={child.kind === 'directory'} class="folder-child-icon" aria-hidden="true"></span><span>{child.path.split('/').at(-1) || child.path}</span></span>
                            {:else}
                              <span class="folder-empty-row">{entry.childSummaryTruncated ? 'Preview limited' : entry.childFileCount === 0 && entry.childFolderCount === 0 ? 'Empty folder' : 'Open to view contents'}</span>
                            {/each}
                            {#if entry.childSummaryTruncated}
                              <span class="folder-more-row">More files &amp; folders</span>
                            {:else if (entry.childFileCount ?? 0) + (entry.childFolderCount ?? 0) > (entry.children?.length ?? 0)}
                              <span class="folder-more-row">+ {(entry.childFileCount ?? 0) + (entry.childFolderCount ?? 0) - (entry.children?.length ?? 0)} more files &amp; folders</span>
                            {/if}
                          </span>
                        {/snippet}
                      </UnifiedEmbedPreview>
                    </div>
                    {/if}
                  {:else}
                    {@const previewEntry = remoteEntryPreview(activeRemoteSource, entry)}
                    {#if viewMode === 'list'}
                      <button class="remote-list-entry" data-testid="project-remote-entry" data-kind="file" type="button" onclick={() => void openRemoteFile(activeRemoteSource, entry.path)}>
                        <span class="remote-list-icon file-icon" aria-hidden="true"></span>
                        <strong>{entry.path.split('/').at(-1) || entry.path}</strong>
                        <small>{entry.sizeBytes === undefined ? 'File' : remoteFileSizeLabel(entry.sizeBytes)}</small>
                      </button>
                    {:else}
                    <div class="remote-file-entry" data-testid="project-remote-entry" data-kind="file">
                      <ProjectRemotePreviewCard
                        preview={previewEntry.preview}
                        sourceLabel={previewEntry.sourceLabel}
                        previewOnly={viewerSplitOpen}
                        imageSrc={remoteImageUrls[`${activeRemoteSource.source_id}:${entry.path}`]}
                        onOpenFullscreen={() => void openRemoteFile(activeRemoteSource, entry.path)}
                        onOpenFile={() => void openRemoteFileDetails(activeRemoteSource, entry.path, entry.sizeBytes)}
                      />
                    </div>
                    {/if}
                  {/if}
                {/each}
                {#if visibleRemoteEntries.length === 0}
                  <p class="muted">No readable entries in this folder.</p>
                {/if}
              </div>
            {/if}
            {#if !isRemoteLoading && (remotePageIndex > 0 || remoteNextCursor)}
              <nav class="files-page-controls" data-testid="project-remote-page-controls" aria-label="Connected folder pages">
                <button type="button" disabled={remotePageIndex === 0} onclick={() => void showRemotePage(remotePageIndex - 1)}>Previous</button>
                <span>Page {remotePageIndex + 1}</span>
                <button type="button" disabled={!remoteNextCursor} onclick={() => void showRemotePage(remotePageIndex + 1)}>Next</button>
              </nav>
            {/if}
            <div class="source-previews">
              {#each remotePreviewEntries.filter((entry) => entry.preview.embed.content.source_id === activeRemoteSource.source_id
                && !remoteEntries.some((remoteEntry) => remoteEntry.path === entry.preview.embed.content.path)) as previewEntry (previewEntry.preview.embed.embed_id)}
                {#if viewMode === 'list'}
                  <button class="remote-list-entry" type="button" onclick={() => void openRemotePreview(previewEntry.preview)}>
                    <span class="remote-list-icon file-icon" aria-hidden="true"></span>
                    <strong>{previewEntry.preview.embed.content.display_name}</strong>
                    <small>File</small>
                  </button>
                {:else}
                <ProjectRemotePreviewCard
                  preview={previewEntry.preview}
                  sourceLabel={previewEntry.sourceLabel}
                  previewOnly={viewerSplitOpen}
                  imageSrc={remoteImageUrls[`${activeRemoteSource.source_id}:${previewEntry.preview.embed.content.path}`]}
                  onOpenFullscreen={() => void openRemotePreview(previewEntry.preview)}
                  onOpenFile={() => void openRemoteFileDetails(activeRemoteSource, previewEntry.preview.embed.content.path, previewEntry.preview.embed.content.size_bytes)}
                />
                {/if}
              {/each}
            </div>
          </div>
        {/if}
        {/if}
        </div>
      </section>


      </section>
      {:else}
      <section class="project-panel tasks-panel" role="tabpanel" id="tabpanel-tasks" data-testid="project-tasks-panel">
        {#key selectedProject.project_id}
          <TasksPage
            projectId={selectedProject.project_id}
            compact
            previewTasks={previewState?.tasks ?? null}
            previewProjectNames={previewState ? { [selectedProject.project_id]: selectedProject.name || 'Untitled project' } : {}}
          />
        {/key}
      </section>
      {/if}
    {:else}
      <div class="empty-state large">
        <h2>Continue where you left off</h2>
        <p>Create your first project to organize chats, embeds, and uploads around a goal.</p>
      </div>
    {/if}
{/snippet}

{#if variant === 'sidebar'}
  <aside class="projects-sidebar-panel" aria-label="Projects" data-testid="projects-sidebar">
    <div class="top-buttons-container">
      <div class="top-buttons">
        <button
          class="clickable-icon icon_close top-button right"
          aria-label="Close projects"
          onclick={() => panelState.closeChats()}
          type="button"
        ></button>
      </div>
    </div>
    <div class="projects-sidebar-scroll">
      <h2 class="group-title">Projects</h2>
      {@render createProjectForm(true)}
      {@render projectList()}
    </div>
  </aside>
{:else}
  <div class="projects-workspace-layout" class:viewer-open={!!activeRemoteFullscreen || !!activeRemoteGenericFile || !!activeRemoteImage || !!activeStoredFullscreen} bind:clientWidth={workspaceWidth}>
    <section class="projects-page" data-testid="projects-page">
      {#if selectedProject}
        <main class="project-main" data-testid="project-management" bind:this={projectMainElement}>
          {@render selectedProjectDetails()}
        </main>
      {:else}
        <WorkspaceHomeShell
          surface="projects"
          testId="projects-start-screen"
          heading={`Hey ${greetingName}!`}
          subtitle="What do you want to organize next?"
          actionItems={projectLandingItems}
          actionItemsTestId="project-mixed-row"
          itemTestId="project-landing-card"
          showReportIssue
          onActionItem={openProjectFromCard}
          onContinueItem={openProjectFromCard}
          onStartInspiration={handleStartProjectInspiration}
        >
          <svelte:fragment slot="composer">
            <WorkspacePromptComposer
              surface="projects"
              bind:value={newProjectName}
              placeholder="Name a new project"
              submitLabel="Create project"
              submittingLabel="Creating..."
              disabled={isSaving}
              submitting={isSaving}
              testId="project-input-composer"
              inputTestId="project-input-textarea"
              submitTestId="project-input-submit"
              micTestId="project-input-mic"
              onSubmit={requestProjectCreation}
              onMicClick={showProjectVoiceInputUnavailable}
            />
          </svelte:fragment>
        </WorkspaceHomeShell>
      {/if}
    </section>

    {#if activeRemoteFullscreen || activeRemoteGenericFile || activeRemoteImage || activeStoredFullscreen}
      <aside class="project-embed-viewer" data-testid="project-embed-viewer" aria-label="Project embed viewer">
        {#if activeRemoteFullscreen}
          <div
            class="projects-remote-fullscreen"
            data-testid="project-remote-fullscreen-overlay"
            onclickcapture={handleRemoteFullscreenClick}
          >
            <CodeEmbedFullscreen
              data={{
                decodedContent: activeRemoteFullscreen.decodedContent,
                attrs: activeRemoteFullscreen.attrs,
                embedData: activeRemoteFullscreen.embedData,
              }}
              embedId={activeRemoteFullscreen.embedId}
              onClose={closeRemotePreview}
              onImport={activeRemoteImportEntry ? importActiveRemotePreview : undefined}
              isImporting={isSaving}
              onDownloadOverride={() => downloadRemoteFile(
                String(activeRemoteFullscreen.decodedContent.source_id || activeRemoteSourceId || ''),
                String(activeRemoteFullscreen.decodedContent.path || ''),
              )}
            />
          </div>
        {:else if activeRemoteImage}
          <div class="projects-remote-fullscreen" data-testid="project-remote-fullscreen-overlay" onclickcapture={handleRemoteFullscreenClick}>
            <ImageEmbedFullscreen
              data={{ decodedContent: {
                src: activeRemoteImage.src,
                filename: activeRemoteImage.filename,
                fileSize: activeRemoteImage.sizeBytes,
              }, attrs: {}, embedData: {} }}
              onClose={closeRemotePreview}
            />
          </div>
        {:else if activeRemoteGenericFile}
          <div class="projects-remote-fullscreen" data-testid="project-remote-fullscreen-overlay" onclickcapture={handleRemoteFullscreenClick}>
            <FileEmbedFullscreen
              data={{ decodedContent: {
                filename: activeRemoteGenericFile.filename,
                normalized_path: activeRemoteGenericFile.path,
                size_bytes: activeRemoteGenericFile.sizeBytes,
                mime_type: 'application/octet-stream',
              }, attrs: {}, embedData: {} }}
              onClose={closeRemotePreview}
              onDownload={remoteDownloadProgress
                ? undefined
                : () => void downloadRemoteFileOrNotify(activeRemoteGenericFile.sourceId, activeRemoteGenericFile.path)}
              downloadUnavailableMessage="Download in progress."
            />
          </div>
        {:else if activeStoredFullscreen}
          {@const decodedContent = storedFullscreenContent(activeStoredFullscreen)}
          {@const registryKey = resolveRegistryKey(
            registryNormalizeEmbedType(activeStoredFullscreen.embedType || ''),
            decodedContent,
          )}
          {#if registryKey && hasFullscreenComponent(registryKey)}
            {#await loadFullscreenComponent(registryKey) then FullscreenComponent}
              {#if FullscreenComponent}
                <FullscreenComponent
                  data={{
                    decodedContent,
                    attrs: activeStoredFullscreen.attrs,
                    embedData: activeStoredFullscreen.embedData,
                  }}
                  embedId={activeStoredFullscreen.embedId || ''}
                  onClose={closeStoredFullscreen}
                  showChatButton={false}
                />
              {/if}
            {/await}
          {/if}
        {/if}
        {#if remoteDownloadProgress}
          <div class="remote-download-status" data-testid="project-remote-download-status" role="status" aria-live="polite">
            <span>
              Downloading {remoteDownloadProgress.path.split('/').pop() || 'file'}:
              {remoteFileSizeLabel(remoteDownloadProgress.downloadedBytes)}
              {#if remoteDownloadProgress.totalBytes > 0}
                of {remoteFileSizeLabel(remoteDownloadProgress.totalBytes)}
              {/if}
            </span>
            <button type="button" onclick={cancelRemoteDownload} data-testid="project-remote-download-cancel">Cancel</button>
          </div>
        {/if}
      </aside>
    {/if}
  </div>
{/if}

{#if pendingProjectName}
  <div class="project-policy-overlay" data-testid="project-write-policy-dialog">
    <div
      class="project-policy-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="project-policy-title"
    >
      <h2 id="project-policy-title">Choose write permissions</h2>
      <p>How may OpenMates change files in <strong>{pendingProjectName}</strong>?</p>
      {@render writePolicyChoice()}
      <div class="project-policy-actions">
        <button class="secondary-action" data-testid="project-write-policy-cancel" type="button" onclick={cancelProjectCreation}>Cancel</button>
        <button data-testid="project-write-policy-confirm" type="button" disabled={isSaving || !newProjectWriteMode} onclick={() => void handleCreateProject()}>
          {isSaving ? 'Creating...' : 'Create project'}
        </button>
      </div>
    </div>
  </div>
{/if}

<svelte:window onkeydown={handleRemoteFullscreenKeydown} />

<style>
  .projects-workspace-layout {
    position: relative;
    display: flex;
    container: project-workspace / inline-size;
    width: 100%;
    height: 100%;
    min-width: 0;
    min-height: 0;
    gap: var(--spacing-5);
  }

  .projects-page {
    position: relative;
    container: project-page / inline-size;
    flex: 1;
    min-width: 0;
    height: 100%;
    overflow: hidden;
    border-radius: 17px;
    background: var(--color-grey-20);
    box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
    color: var(--color-font-primary);
    font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
  }

  .project-embed-viewer {
    position: absolute;
    inset: 0;
    z-index: var(--z-index-modal);
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-lg);
  }

  .remote-download-status {
    position: absolute;
    z-index: 2;
    inset-inline: var(--spacing-12);
    bottom: var(--spacing-12);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--spacing-8);
    padding: var(--spacing-8) var(--spacing-12);
    border-radius: var(--radius-8);
    background: var(--color-grey-10);
    box-shadow: var(--shadow-lg);
    color: var(--color-font-primary);
  }

  .remote-download-status button {
    border: 0;
    border-radius: var(--radius-8);
    padding: var(--spacing-4) var(--spacing-8);
    background: var(--color-grey-25);
    color: var(--color-font-primary);
    cursor: pointer;
  }

  @container project-workspace (min-width: 1024px) {
    .projects-workspace-layout.viewer-open .projects-page {
      flex: 0 0 25rem;
      width: 25rem;
      max-width: 25rem;
    }

    .project-embed-viewer {
      position: relative;
      inset: auto;
      z-index: auto;
      flex: 1 1 auto;
    }
  }

  .projects-sidebar-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    width: 100%;
    overflow: hidden;
    background: var(--color-grey-20);
  }

  .projects-sidebar-scroll {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding-bottom: var(--spacing-10);
  }

  .top-buttons-container {
    flex-shrink: 0;
    z-index: var(--z-index-dropdown-1);
    background-color: var(--color-grey-20);
    padding: var(--spacing-8) var(--spacing-10);
    border-bottom: 1px solid var(--color-grey-30);
  }

  .top-buttons {
    position: relative;
    height: 32px;
    display: flex;
    justify-content: flex-end;
  }

  .top-button.right {
    margin-inline-start: auto;
  }

  .group-title {
    font-size: 0.85em;
    color: var(--color-grey-60);
    margin: 0 0 var(--spacing-3);
    padding: 15px 15px 0;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .project-section h2,
  .project-section h3 {
    margin: 0;
  }

  .muted {
    color: var(--color-font-secondary);
  }

  .create-row {
    display: flex;
    gap: 8px;
    margin: 20px 15px;
  }

  .create-row.compact {
    margin: 10px 15px 20px;
    flex-direction: column;
  }

  .write-policy-choice {
    display: grid;
    gap: var(--spacing-3);
    min-width: 0;
    margin: 0;
    padding: var(--spacing-4);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-4);
    background: var(--color-grey-10);
  }

  .write-policy-choice legend {
    padding: 0 var(--spacing-2);
    color: var(--color-font-secondary);
    font-size: var(--processing-details-font-size);
  }

  .write-policy-choice label {
    display: flex;
    align-items: flex-start;
    gap: var(--spacing-3);
    cursor: pointer;
  }

  .write-policy-choice label input {
    flex: 0 0 auto;
    width: 1rem;
    min-width: 1rem;
    padding: 0;
    border: 0;
    margin-top: var(--spacing-1);
    accent-color: var(--color-button-primary);
  }

  .write-policy-choice label span {
    display: grid;
    gap: var(--spacing-1);
  }

  .write-policy-choice small {
    color: var(--color-font-secondary);
  }

  .project-policy-overlay {
    position: fixed;
    inset: 0;
    z-index: var(--z-index-popover);
    display: grid;
    place-items: center;
    padding: var(--spacing-5);
    background: color-mix(in srgb, var(--color-grey-0) 70%, transparent);
  }

  .project-policy-dialog {
    display: grid;
    gap: var(--spacing-4);
    width: min(100%, 560px);
    padding: var(--spacing-6);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-5);
    background: var(--color-grey-20);
    box-shadow: var(--shadow-lg);
  }

  .project-policy-dialog h2,
  .project-policy-dialog p {
    margin: 0;
  }

  .project-policy-actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--spacing-3);
  }

  .project-policy-actions .secondary-action {
    background: var(--color-grey-30);
    color: var(--color-font-primary);
  }

  input {
    flex: 1;
    min-width: 0;
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-3);
    padding: 10px 12px;
    font: inherit;
  }

  button {
    border: 0;
    border-radius: var(--radius-3);
    padding: 10px 14px;
    background: var(--color-button-primary);
    color: var(--color-font-button);
    font: inherit;
    cursor: pointer;
  }

  button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .project-list {
    display: grid;
    gap: var(--spacing-2);
    padding: 0 10px;
  }

  .project-card {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
    background: transparent;
    color: inherit;
    border: 0;
    border-radius: var(--radius-3);
    text-align: left;
    padding: 0;
  }

  .project-card > button {
    display: flex;
    flex: 1;
    align-items: center;
    gap: var(--spacing-3);
    background: transparent;
    color: inherit;
    text-align: left;
  }

  .sidebar-project-icon {
    display: grid;
    width: 2.25rem;
    height: 2.25rem;
    flex: 0 0 auto;
    place-items: center;
    overflow: hidden;
    border-radius: var(--radius-full);
    background: linear-gradient(135deg, var(--color-app-weather-start), var(--color-app-weather-end));
    color: transparent;
  }

  .sidebar-project-icon::before {
    width: 1.125rem;
    height: 1.125rem;
    background: var(--color-font-button);
    content: '';
    -webkit-mask: var(--icon-url-files) center / contain no-repeat;
    mask: var(--icon-url-files) center / contain no-repeat;
  }

  .sidebar-project-copy {
    display: grid;
    min-width: 0;
    gap: var(--spacing-1);
  }

  .sidebar-project-copy strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .project-card > a {
    min-width: 44px;
    min-height: 44px;
    display: grid;
    place-items: center;
    color: var(--color-font-primary);
  }

  .project-card.active {
    background: color-mix(in srgb, var(--color-grey-60) 30%, transparent);
  }

  .project-main {
    width: 100%;
    height: 100%;
    overflow: auto;
    padding: 0;
    box-sizing: border-box;
  }

  .project-tabs {
    position: relative;
    z-index: var(--z-index-raised-3);
    width: min(13.75rem, calc(100% - var(--spacing-12)));
    margin: var(--spacing-10) auto 0;
    transform: translateY(0.9rem);
  }

  .project-tabs :global(.settings-tabs-wrapper) { padding: 0; }
  .project-tabs :global(.settings-tab.active .tab-icon) { background-color: var(--color-white-fixed, #fff); }

  .project-panel {
    position: relative;
    box-sizing: border-box;
    width: min(64rem, calc(100% - clamp(var(--spacing-8), 5vw, var(--spacing-20))));
    min-height: 20rem;
    margin: calc(var(--spacing-4) * -1) auto var(--spacing-8);
    padding: clamp(var(--spacing-12), 4vw, var(--spacing-24));
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-sm);
  }

  .overview-panel {
    display: grid;
    min-height: 19.5rem;
    place-items: center;
  }

  .overview-panel :global(.project-readme) { border: 0; }

  .folders-panel { width: min(80rem, calc(100% - clamp(var(--spacing-8), 5vw, var(--spacing-20)))); max-width: 80rem; }
  .tasks-panel { max-width: 64rem; padding: var(--spacing-8); overflow-x: auto; }

  .folder-summary-row {
    display: grid;
    grid-template-columns: 1fr minmax(12rem, 20rem) 1fr;
    align-items: center;
    gap: var(--spacing-8);
    margin-bottom: var(--spacing-8);
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }

  .folder-search {
    display: flex;
    align-items: center;
    justify-self: center;
    gap: var(--spacing-3);
    width: auto;
  }

  .folder-search input {
    width: 5rem;
    flex: 0 0 auto;
    border: 0;
    border-radius: 0;
    padding: var(--spacing-3) 0;
    background: transparent;
    box-shadow: none;
    text-align: center;
  }

  .sort-button {
    justify-self: end;
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    padding: 0;
    background: transparent;
    box-shadow: none;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }

  .search-icon,
  .sort-icon,
  .tray-icon,
  .menu-icon {
    display: inline-block;
    flex: 0 0 auto;
    width: 1.25rem;
    height: 1.25rem;
    background: currentColor;
    -webkit-mask: var(--project-action-icon) center / contain no-repeat;
    mask: var(--project-action-icon) center / contain no-repeat;
  }

  .search-icon { --project-action-icon: var(--icon-url-search); }
  .sort-icon { --project-action-icon: var(--icon-url-sort); color: var(--color-primary); }
  .sort-button .sort-icon {
    position: relative;
    width: 2.5rem;
    height: 2.5rem;
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
    box-shadow: var(--shadow-sm);
    -webkit-mask: none;
    mask: none;
  }
  .sort-button .sort-icon::after {
    position: absolute;
    inset: var(--spacing-4);
    background: var(--color-primary);
    content: '';
    -webkit-mask: var(--icon-url-sort) center / contain no-repeat;
    mask: var(--icon-url-sort) center / contain no-repeat;
  }
  .sync-icon { --project-action-icon: var(--icon-url-reload); }
  .upload-icon { --project-action-icon: var(--icon-url-upload); }
  .chat-icon { --project-action-icon: var(--icon-url-chat); }
  .workflow-icon { --project-action-icon: var(--icon-url-workflow); }
  .plan-icon { --project-action-icon: var(--icon-url-planning); }

  .project-actions {
    display: inline-flex;
    min-height: 10rem;
    align-items: center;
    margin: 0;
    border-radius: var(--radius-5);
    background: var(--color-grey-10);
  }

  .project-action-expander {
    display: grid;
    min-width: 0;
    width: fit-content;
  }

  .browser-grid > .project-action-expander.expanded {
    grid-column: 1 / -1;
    width: 100%;
    grid-template-columns: minmax(16rem, 1fr) minmax(0, 2fr);
    border-radius: var(--radius-5);
    background: var(--color-grey-10);
    overflow: hidden;
  }

  .browser-list > .project-action-expander.expanded {
    width: 100%;
    grid-template-columns: minmax(16rem, 1fr) minmax(0, 2fr);
    border-radius: var(--radius-5);
    background: var(--color-grey-10);
  }

  .project-actions button {
    display: grid;
    min-width: 6rem;
    min-height: 7rem;
    place-items: center;
    align-content: center;
    gap: var(--spacing-4);
    border-inline-end: 1px solid var(--color-grey-30);
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    font-weight: 700;
  }

  .project-actions button:last-child { border-inline-end: 0; }
  .project-actions .tray-icon { width: 1.75rem; height: 1.75rem; }
  .project-actions button > .tray-icon,
  .project-actions button > .project-create-action-icon {
    justify-self: center;
    margin-inline: auto;
  }
  .project-actions button,
  .project-actions button > .tray-icon,
  .project-actions button > .project-create-action-icon {
    filter: none;
    text-shadow: none;
  }
  .project-actions .project-create-action-icon {
    width: 1.75rem;
    height: 1.75rem;
    flex: 0 0 auto;
    background: currentColor;
  }

  .create-menu {
    position: absolute;
    z-index: var(--z-index-dropdown-1);
    inset-inline-start: 50%;
    inset-block-end: var(--spacing-8);
    display: grid;
    width: min(24rem, calc(100% - var(--spacing-12)));
    transform: translateX(-50%);
    overflow: hidden;
    border: 1px solid var(--color-grey-25);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-lg);
  }

  .create-menu.folder-create-menu {
    position: static;
    inset: auto;
    width: 100%;
    margin: 0;
    transform: none;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    grid-auto-rows: 1fr;
    min-height: 10rem;
    border: 0;
    border-inline-start: 1px solid var(--color-grey-30);
    border-radius: 0;
    background: transparent;
    box-shadow: none;
  }

  .create-menu.folder-create-menu button {
    display: grid;
    place-content: center;
    justify-items: center;
    align-content: center;
    gap: var(--spacing-4);
    min-width: 0;
    min-height: 10rem;
    color: var(--color-font-secondary);
    text-align: center;
  }

  .create-menu.folder-create-menu .menu-icon { width: 1.75rem; height: 1.75rem; }

  .create-menu button {
    display: flex;
    align-items: center;
    gap: var(--spacing-6);
    padding: var(--spacing-6);
    border-radius: 0;
    background: transparent;
    color: var(--color-font-primary);
    text-align: start;
  }

  .create-menu button + button { border-top: 1px solid var(--color-grey-25); }
  .create-menu.folder-create-menu button + button { border-top: 0; border-inline-start: 1px solid var(--color-grey-25); }
  .create-menu button:hover { background: var(--color-grey-10); }
  .create-menu button > span:last-child { display: grid; gap: var(--spacing-2); }
  .create-menu small { color: var(--color-font-secondary); }
  .legacy-empty-contract { position: absolute; width: 1px; height: 1px; overflow: hidden; }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  .section-title {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--spacing-8);
    margin-bottom: 24px;
  }

  .project-section {
    margin-top: 32px;
  }

  .browser-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 16px;
  }

  .view-toggle {
    display: inline-flex;
    gap: 4px;
    padding: 4px;
    border-radius: var(--radius-4);
    background: var(--color-grey-10);
  }

  .view-toggle button {
    background: transparent;
    color: var(--color-font-secondary);
    padding: 7px 10px;
  }

  .view-toggle button.active {
    background: var(--color-grey-0);
    color: var(--color-font-primary);
  }

  .browser-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 16px;
  }

  .browser-list {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }

  .files-page-controls {
    grid-column: 1 / -1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-5);
    padding: var(--spacing-5) 0;
    color: var(--color-font-secondary);
  }

  .files-page-controls button {
    min-height: 2.75rem;
    padding: 0 var(--spacing-5);
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: var(--color-grey-10);
    color: var(--color-font-primary);
  }

  .files-page-controls button:disabled { opacity: 0.45; cursor: default; }
  .files-page-controls button:focus-visible { outline: 2px solid var(--color-focus, var(--color-font-primary)); }

  .project-search-results { display: contents; }
  .search-section-heading { grid-column: 1 / -1; margin: var(--spacing-5) 0 0; }
  .search-result-card { width: min(18.75rem, 100%); min-width: 0; justify-self: center; }
  .search-result-location {
    display: block;
    overflow: hidden;
    padding: var(--spacing-2) var(--spacing-3);
    color: var(--color-font-secondary);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .remote-list-entry {
    display: grid;
    grid-template-columns: 1.5rem minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--spacing-5);
    width: 100%;
    min-height: 4rem;
    padding: var(--spacing-4) var(--spacing-7);
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: none;
    color: var(--color-font-primary);
    text-align: start;
  }

  .remote-list-entry strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .remote-list-entry small { color: var(--color-font-secondary); }
  .remote-list-entry:focus-visible { outline: 2px solid var(--color-focus, var(--color-font-primary)); }
  .remote-list-icon { width: 1.25rem; height: 1.25rem; background: var(--color-font-secondary); }
  .remote-list-icon.folder-list-icon { -webkit-mask: var(--icon-url-files) center / contain no-repeat; mask: var(--icon-url-files) center / contain no-repeat; }
  .remote-list-icon.file-icon { -webkit-mask: var(--icon-url-code, var(--icon-url-files)) center / contain no-repeat; mask: var(--icon-url-code, var(--icon-url-files)) center / contain no-repeat; }

  .folder-entry,
  .source-root-entry {
    color: inherit;
    text-align: left;
    border: 0;
    border-radius: var(--radius-5);
    background: var(--color-grey-20);
    box-shadow: var(--shadow-md);
  }

  .folder-entry.list,
  .source-root-entry.list {
    display: grid;
    grid-template-columns: minmax(90px, 140px) 1fr auto;
    align-items: center;
    min-height: 64px;
    padding: 0 14px;
    box-shadow: none;
  }

  .folder-icon {
    color: var(--color-font-secondary);
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .folder-preview {
    display: flex;
    min-width: 0;
    justify-content: center;
  }

  .folder-preview.remote-preview-badged,
  .folder-entry.remote-preview-badged,
  .source-root-entry.remote-preview-badged {
    position: relative;
  }

  .folder-preview.remote-preview-badged {
    width: fit-content;
    max-width: 100%;
    justify-self: center;
  }

  .remote-cloud-badge {
    position: absolute;
    inset-block-start: var(--spacing-3);
    inset-inline-end: var(--spacing-3);
    z-index: 2;
    width: 1.25rem;
    height: 1.25rem;
    border-radius: var(--radius-full);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-sm);
    pointer-events: none;
  }

  .remote-cloud-badge::after {
    position: absolute;
    inset: 0.2rem;
    background: var(--color-font-secondary);
    content: '';
    -webkit-mask: var(--icon-url-cloud) center / contain no-repeat;
    mask: var(--icon-url-cloud) center / contain no-repeat;
  }

  .folder-preview :global(.unified-embed-preview) {
    flex: 0 0 auto;
  }

  .folder-child-row > span:nth-child(2) {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .folder-child-icon {
    display: inline-block;
    flex: 0 0 auto;
    background: currentColor;
    -webkit-mask: var(--icon-url-files) center / contain no-repeat;
    mask: var(--icon-url-files) center / contain no-repeat;
  }

  .folder-child-icon { width: 0.9rem; height: 0.9rem; color: var(--color-font-secondary); }
  .folder-child-icon:not(.child-folder) { -webkit-mask: var(--icon-url-code, var(--icon-url-files)) center / contain no-repeat; mask: var(--icon-url-code, var(--icon-url-files)) center / contain no-repeat; }

  .folder-card-contents {
    display: grid;
    align-content: center;
    gap: var(--spacing-2);
    min-width: 0;
    padding: var(--spacing-8) var(--spacing-12);
  }

  .folder-child-row {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--spacing-2);
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }

  .folder-child-row small { color: inherit; font-size: 0.72rem; }
  .folder-empty-row { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
  .folder-more-row { color: var(--color-font-secondary); font-size: var(--font-size-xs); font-weight: 700; }

  .source-root-entry {
    text-align: left;
    background: var(--color-grey-0);
  }

  .source-root-entry:disabled {
    cursor: not-allowed;
    opacity: 0.68;
  }

  .source-root-icon {
    color: var(--color-font-secondary);
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .project-breadcrumbs {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: var(--spacing-2);
    overflow: hidden;
  }

  .breadcrumb-button {
    padding: 0;
    background: transparent;
    color: var(--color-font-secondary);
  }

  .breadcrumb-separator,
  .breadcrumb-current {
    color: var(--color-font-secondary);
    font-size: 0.9rem;
  }

  .empty-state {
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    padding: 18px;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
  }

  .empty-state.large {
    max-width: 520px;
    margin: 12vh auto;
    text-align: center;
  }

  .source-previews {
    display: contents;
  }

  .remote-browser {
    display: contents;
  }

  .remote-results {
    display: contents;
  }

  .remote-file-entry {
    width: min(18.75rem, 100%);
    min-width: 0;
    justify-self: center;
  }

  .remote-file-entry :global(.remote-preview-card) {
    width: 100%;
  }


  .remote-error {
    margin: 0;
    color: var(--color-error);
  }

  .projects-remote-fullscreen {
    position: relative;
    inset: 0;
    width: 100%;
    height: 100%;
    background: var(--color-grey-0);
  }

  @container project-page (max-width: 1199px) {
    .browser-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }

  @container project-page (max-width: 700px) {
    .browser-grid { grid-template-columns: minmax(0, 1fr); }
  }

  @container project-page (max-width: 500px) {
    .project-panel {
      width: calc(100% - var(--spacing-4));
      padding-inline: var(--spacing-5);
    }

    .remote-list-entry { grid-template-columns: 1.5rem minmax(0, 1fr); }
    .remote-list-entry small { display: none; }

    .folder-summary-row {
      grid-template-columns: 1fr auto;
      gap: var(--spacing-4);
    }

    .folder-search {
      grid-column: 1 / -1;
      grid-row: 2;
    }

    .browser-grid {
      grid-template-columns: minmax(0, 1fr);
    }

    .remote-file-entry,
    .source-previews :global(.remote-preview-card) {
      width: 100%;
    }
  }

  .folders-panel.viewer-split-open .folder-summary-row,
  .folders-panel.viewer-split-open .browser-grid > .folder-preview,
  .folders-panel.viewer-split-open .browser-grid > .source-root-entry,
  .folders-panel.viewer-split-open .browser-grid > .empty-state,
  .folders-panel.viewer-split-open .remote-browser > :not(.remote-results):not(.source-previews) {
    display: none;
  }

  .folders-panel.viewer-split-open .browser-grid,
  .folders-panel.viewer-split-open .remote-results,
  .folders-panel.viewer-split-open .source-previews {
    grid-template-columns: minmax(0, 1fr);
  }

  .folders-panel.viewer-split-open .remote-browser {
    margin-top: var(--spacing-4);
    padding: 0;
    gap: var(--spacing-4);
    background: transparent;
  }

  .folders-panel.viewer-split-open .remote-file-entry,
  .folders-panel.viewer-split-open .source-previews :global(.remote-preview-card) {
    width: min(18.75rem, 100%);
    justify-self: center;
  }

  .load-error {
    margin: 0 15px;
    color: var(--color-font-secondary);
  }

  @media (max-width: 800px) {
    .section-title {
      flex-direction: column;
      align-items: stretch;
    }

    .browser-grid {
      grid-template-columns: 1fr;
    }

    .project-main { padding: 0; }
    .project-panel { width: calc(100% - var(--spacing-4)); min-height: 18rem; padding: var(--spacing-8) var(--spacing-5); }
    .folder-summary-row { grid-template-columns: 1fr auto; }
    .folder-search { grid-column: 1 / -1; grid-row: 2; }
    .folder-search input { text-align: start; }
    .project-actions { width: 100%; min-height: 8rem; }
    .project-actions button { min-width: 0; min-height: 6rem; flex: 1; }
    .browser-grid > .project-action-expander.expanded,
    .browser-list > .project-action-expander.expanded { grid-template-columns: 1fr; }
    .create-menu.folder-create-menu { min-height: 7rem; border-inline-start: 0; border-top: 1px solid var(--color-grey-30); }
    .create-menu.folder-create-menu button { min-height: 7rem; }

  }
</style>
