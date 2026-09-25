<!--
  ProjectsPage.svelte
  Projects V1 workspace UI for manually organizing chats, embeds, and uploads.
  Files uploaded here are converted into embeds first and then linked through
  project_items, so project storage follows the same encryption/rendering model
  as the rest of OpenMates.
-->

<script lang="ts">
  import { onMount, setContext } from 'svelte';
  import { pushState, replaceState } from '$app/navigation';
  import { text } from '@repo/ui';
  import { SettingsTabs } from '../settings/elements';
  import UnifiedEmbedPreview from '../embeds/UnifiedEmbedPreview.svelte';
  import CodeEmbedFullscreen from '../embeds/code/CodeEmbedFullscreen.svelte';
  import ProjectBrowserItem from './ProjectBrowserItem.svelte';
  import ProjectReadme from './ProjectReadme.svelte';
  import ProjectWorkspaceHeader from './ProjectWorkspaceHeader.svelte';
  import ProjectRemotePreviewCard from './ProjectRemotePreviewCard.svelte';
  import TasksPage from '../tasks/TasksPage.svelte';
  import type { TasksBoardItem } from '../../services/userTaskService';
  import WorkspaceHomeShell from '../workspace/WorkspaceHomeShell.svelte';
  import WorkspacePromptComposer from '../workspace/WorkspacePromptComposer.svelte';
  import { notificationStore } from '../../stores/notificationStore';
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
    type ProjectRemoteSearchMatch,
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
  import { loadProjectReadme, releaseProjectReadmeImages, type ProjectReadmeState } from '../../services/projectReadme';

  type ProjectTab = 'overview' | 'folders' | 'tasks';

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
  let activeStoredFullscreen = $state<EmbedFullscreenDispatchDetail | null>(null);
  let projectHashId = $state<string | null>(null);
  let activeRemoteSourceId = $state<string | null>(null);
  let remotePath = $state('.');
  let remoteEntries = $state<ProjectRemoteDirectoryEntry[]>([]);
  let remoteSearchQuery = $state('');
  let remoteSearchMatches = $state<ProjectRemoteSearchMatch[]>([]);
  let remoteOmittedCount = $state(0);
  let remoteExcludedCount = $state(0);
  let remotePreviewEntries = $state<RemotePreviewEntry[]>([]);
  let remoteError = $state('');
  let isRemoteLoading = $state(false);
  let remoteRequestController: AbortController | null = null;
  let remoteRequestGeneration = 0;
  let activeTab = $state<ProjectTab>('overview');
  let readmeState = $state<ProjectReadmeState>({ status: 'loading' });
  let folderSearchQuery = $state('');
  let sortNewestFirst = $state(true);
  let showCreateMenu = $state(false);
  let workspaceWidth = $state(0);
  let projectMainElement = $state<HTMLElement>();
  let viewerSplitOpen = $derived(workspaceWidth >= 1024 && (!!activeRemoteFullscreen || !!activeStoredFullscreen));

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
  let browserFolders = $derived(currentVirtualPath === null
    ? folders.filter((folder) => (folder.parentHash ?? null) === currentFolderHash)
    : []);
  let browserVirtualFolders = $derived(currentFolderHash === null ? virtualBrowserView.folders : []);
  let browserItems = $derived(currentFolderHash === null
    ? virtualBrowserView.items
    : items.filter((item) => (item.encrypted.hashed_folder_id ?? null) === currentFolderHash));
  let browserSources = $derived(currentFolderHash === null && currentVirtualPath === null ? sources : []);
  let projectLandingItems = $derived<ProjectContinueItem[]>(recentProjects.map((project) => ({
    id: project.project_id,
    title: project.name || 'Untitled project',
    summary: `${project.encrypted.item_count ?? 0} items`,
    badge: 'Project',
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
  let activeRemoteSource = $derived(sources.find((source) => source.source_id === activeRemoteSourceId) ?? null);

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
      readmeState = { status: 'loading' };
      resetRemoteBrowser();
      return;
    }
    const project = selectedProject;
    readmeState = { status: 'loading' };
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
    if (selectedProject?.project_id !== project.project_id) {
      if (loadedReadme.status === 'ready') releaseProjectReadmeImages(loadedReadme.document);
      return;
    }
    readmeState = loadedReadme;
  }

  async function retryProjectReadme(): Promise<void> {
    try {
      await refreshSelectedProject();
    } catch (error) {
      console.error('[ProjectsPage] Failed to retry the project overview:', error);
      readmeState = { status: 'error', message: 'Could not load the project overview. Please try again.' };
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
    readmeState = { status: 'loading' };
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

  function closeRemotePreview(): void {
    const closingEmbedId = activeRemoteFullscreen?.embedId;
    activeRemoteFullscreen = null;
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
    if (!activeRemoteFullscreen) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('[data-testid="embed-minimize"]')) {
      closeRemotePreview();
    }
  }

  function handleRemoteFullscreenKeydown(event: KeyboardEvent): void {
    if (!activeRemoteFullscreen || event.key !== 'Escape') return;
    closeRemotePreview();
  }

  function resetRemoteBrowser(): void {
    remoteRequestController?.abort();
    remoteRequestController = null;
    remoteRequestGeneration += 1;
    activeRemoteFullscreen = null;
    activeStoredFullscreen = null;
    activeRemoteSourceId = null;
    remotePath = '.';
    remoteEntries = [];
    remoteSearchQuery = '';
    remoteSearchMatches = [];
    remoteOmittedCount = 0;
    remoteExcludedCount = 0;
    remotePreviewEntries = [];
    remoteError = '';
    isRemoteLoading = false;
  }

  function clearRemoteNavigation(): void {
    remoteRequestController?.abort();
    remoteRequestController = null;
    remoteRequestGeneration += 1;
    activeRemoteFullscreen = null;
    activeRemoteSourceId = null;
    remotePath = '.';
    remoteEntries = [];
    remoteSearchQuery = '';
    remoteSearchMatches = [];
    remoteOmittedCount = 0;
    remoteExcludedCount = 0;
    remotePreviewEntries = [];
    remoteError = '';
    isRemoteLoading = false;
  }

  function beginRemoteRequest(): { controller: AbortController; generation: number; projectId: string | null } {
    remoteRequestController?.abort();
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
    return error instanceof Error ? error.message : fallback;
  }

  async function refreshRemoteSourceStatus(): Promise<void> {
    const project = selectedProject;
    if (!project) return;
    try {
      const refreshed = await listProjectSources(project);
      if (selectedProject?.project_id !== project.project_id) return;
      sources = refreshed;
      const active = refreshed.find((source) => source.source_id === activeRemoteSourceId);
      if (activeRemoteSourceId && (!active || active.status !== 'connected')) {
        remoteRequestController?.abort();
        remoteRequestController = null;
        remoteRequestGeneration += 1;
        activeRemoteFullscreen = null;
        remoteEntries = [];
        remoteSearchMatches = [];
        remotePreviewEntries = [];
        remoteOmittedCount = 0;
        remoteExcludedCount = 0;
        isRemoteLoading = false;
        remoteError = active ? 'This Project source is offline' : 'This Project source is no longer available';
      }
    } catch (error) {
      console.error('[ProjectsPage] Failed to refresh remote source status:', error);
    }
  }

  async function browseRemoteSource(source: ProjectSourceViewModel, path = '.'): Promise<void> {
    if (!selectedProject) return;
    currentFolder = null;
    currentFolderTrail = [];
    currentFolderHash = null;
    currentVirtualPath = null;
    activeRemoteSourceId = source.source_id;
    activeRemoteFullscreen = null;
    remotePreviewEntries = [];
    if (previewState?.remoteEntries) {
      remotePath = path;
      remoteEntries = previewState.remoteEntries;
      remoteSearchMatches = [];
      remoteOmittedCount = 0;
      remoteExcludedCount = 0;
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
        { path },
        request.controller.signal,
      );
      if (!isCurrentRemoteRequest(request, source.source_id)) return;
      remotePath = path;
      remoteEntries = result.entries;
      remoteSearchMatches = [];
      remoteOmittedCount = result.omitted;
      remoteExcludedCount = result.excluded;
    } catch (error) {
      const message = remoteRequestError(error, 'Could not browse this source');
      if (!message || !isCurrentRemoteRequest(request, source.source_id)) return;
      remoteError = message;
      console.error('[ProjectsPage] Failed to browse remote source:', error);
    } finally {
      finishRemoteRequest(request);
    }
  }

  function remoteParentPath(path: string): string {
    if (!path || path === '.') return '.';
    const parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
    parts.pop();
    return parts.join('/') || '.';
  }

  function remotePathBreadcrumbs(path: string): Array<{ label: string; path: string }> {
    const parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
    return parts.map((label, index) => ({ label, path: parts.slice(0, index + 1).join('/') }));
  }

  async function openRemoteEntry(source: ProjectSourceViewModel, entry: ProjectRemoteDirectoryEntry): Promise<void> {
    if (entry.kind === 'directory') {
      await browseRemoteSource(source, entry.path);
      return;
    }
    await openRemoteFile(source, entry.path);
  }

  async function searchRemoteSource(source: ProjectSourceViewModel): Promise<void> {
    const query = remoteSearchQuery.trim();
    if (!selectedProject || !$userProfile.user_id || !query) return;
    activeRemoteSourceId = source.source_id;
    const request = beginRemoteRequest();
    isRemoteLoading = true;
    remoteError = '';
    try {
      const result = await requestProjectRemoteAccess<ProjectRemoteSearchResult>(
        selectedProject,
        source,
        { ownerId: $userProfile.user_id, teamId: getActiveTeamContextSnapshot().teamId },
        'search',
        { query },
        request.controller.signal,
      );
      if (!isCurrentRemoteRequest(request, source.source_id)) return;
      remoteSearchMatches = result.matches;
      remoteOmittedCount = result.omitted;
      remoteExcludedCount = result.excluded;
    } catch (error) {
      const message = remoteRequestError(error, 'Could not search this source');
      if (!message || !isCurrentRemoteRequest(request, source.source_id)) return;
      remoteError = message;
      console.error('[ProjectsPage] Failed to search remote source:', error);
    } finally {
      finishRemoteRequest(request);
    }
  }

  async function openRemoteFile(source: ProjectSourceViewModel, path: string): Promise<void> {
    if (!selectedProject) return;
    const classification = classifyRemotePreviewPath(path);
    if (classification.kind === 'unsupported') {
      remoteError = $text('projects.remote_preview_unsupported');
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
    const componentPreviewContent = previewState?.remoteEntries
      ? (entry.path.endsWith('.md')
        ? '# Connected project file\n\nThis preview is loaded from the connected source.'
        : 'export const connectedProjectFile = true;')
      : '';
    return {
      preview: normalizeRemoteFilePreview({
        sourceId: source.source_id,
        path: entry.path,
        displayName: entry.path.split('/').filter(Boolean).pop() || entry.path,
        language: classification.kind === 'unsupported' ? 'text' : classification.language,
        snippet: componentPreviewContent,
        snippetTruncated: false,
        sizeBytes: componentPreviewContent ? new TextEncoder().encode(componentPreviewContent).byteLength : undefined,
        lineCount: componentPreviewContent ? componentPreviewContent.split('\n').length : undefined,
        previewPolicy: 'bounded_full_text',
        safetyFlags: [],
      }),
      readResult: null,
      canImport: false,
      sourceLabel: source.displayName || source.source_id,
    };
  }

  async function openFolder(folder: ProjectFolderViewModel): Promise<void> {
    clearRemoteNavigation();
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
    currentFolder = null;
    currentFolderTrail = [];
    currentFolderHash = null;
    currentVirtualPath = folder.path;
  }

  function openRoot(): void {
    clearRemoteNavigation();
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
    if (previewState) {
      projects = [previewState.project];
      selectedProject = previewState.project;
      folders = previewState.folders ?? [];
      items = previewState.items ?? [];
      sources = previewState.sources ?? [];
      readmeState = previewState.readme ?? { status: 'empty' };
      activeTab = initialTab;
      isLoading = false;
      return;
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
      remoteRequestController?.abort();
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
          <strong>{browserFolders.length + browserVirtualFolders.length} folders, {browserItems.length} embeds</strong>
          <label class="folder-search">
            <span class="search-icon" aria-hidden="true"></span>
            <span class="sr-only">Search project files</span>
            <input bind:value={folderSearchQuery} type="search" placeholder="Search" data-testid="project-folder-search" />
          </label>
          <button class="sort-button" type="button" data-testid="project-folder-sort" aria-label={sortNewestFirst ? 'Show oldest first' : 'Show most recent first'} onclick={() => (sortNewestFirst = !sortNewestFirst)}>
            <span>{sortNewestFirst ? 'Most recent first' : 'Oldest first'}</span>
            <span class="sort-icon" aria-hidden="true"></span>
          </button>
        </div>

        {#if showCreateMenu}
          <div class="create-menu folder-create-menu" data-testid="project-create-menu">
            <button type="button" data-testid="project-create-chat" onclick={startProjectChat}><span class="menu-icon chat-icon" aria-hidden="true"></span><span><strong>New chat</strong></span></button>
            <button type="button" data-testid="project-create-workflow" onclick={startProjectWorkflow}><span class="menu-icon workflow-icon" aria-hidden="true"></span><span><strong>New workflow</strong></span></button>
            <button type="button" data-testid="project-create-plan" onclick={startProjectPlan}><span class="menu-icon plan-icon" aria-hidden="true"></span><span><strong>New plan</strong></span></button>
          </div>
        {/if}

      <section class="project-section">
        {#if currentFolder || currentVirtualPath !== null}
          <div class="section-title">
            <div>
              <h3>{currentVirtualPath?.split('/').at(-1) || currentFolder?.name || 'Untitled folder'}</h3>
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
              </nav>
            </div>
          </div>

          <div class="browser-toolbar">
            <span class="muted">{browserFolders.length + browserVirtualFolders.length + browserItems.length + browserSources.length} entries</span>
            <div class="view-toggle" aria-label="Project view mode">
              <button type="button" class:active={viewMode === 'tile'} onclick={() => (viewMode = 'tile')}>Tile</button>
              <button type="button" class:active={viewMode === 'list'} onclick={() => (viewMode = 'list')}>List</button>
            </div>
          </div>
        {/if}

        <div class:browser-grid={viewMode === 'tile'} class:browser-list={viewMode === 'list'} data-testid="project-browser-list">
            <div class="project-actions" data-testid="project-folder-actions">
              <button type="button" onclick={() => void refreshSelectedProject()} disabled={isSaving}>
                <span class="tray-icon sync-icon" aria-hidden="true"></span><span>Sync</span>
              </button>
              <button type="button" onclick={() => uploadInput?.click()} disabled={isSaving} data-testid="project-upload-button">
                <span class="tray-icon upload-icon" aria-hidden="true"></span><span>Upload</span>
              </button>
              <button type="button" onclick={() => (showCreateMenu = !showCreateMenu)} data-testid="project-folder-create-menu-button">
                <span class="clickable-icon icon_create project-create-action-icon" aria-hidden="true"></span><span>Create</span>
              </button>
            </div>
            {#if visibleBrowserFolders.length === 0 && visibleVirtualFolders.length === 0 && visibleBrowserItems.length === 0 && visibleBrowserSources.length === 0}
              <div class="empty-state" data-testid="project-empty-items">
                <h3>{normalizedFolderSearch ? 'No matching project items' : 'No project items yet'}</h3>
                <p>{normalizedFolderSearch ? 'Try a different search.' : 'Upload a file or use “Add to project” from chats and embed fullscreen views.'}</p>
              </div>
            {/if}
            {#each visibleBrowserFolders as folder (folder.folder_id)}
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
            {#each visibleVirtualFolders as folder (folder.path)}
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
            {#each visibleBrowserItems as item (item.project_item_id)}
              <ProjectBrowserItem
                {item}
                {viewMode}
                displayName={projectBrowserItemName(item)}
                loadProjectEmbed={loadProjectEmbed}
                onOpenFullscreen={openStoredFullscreen}
              />
            {/each}
            {#each visibleBrowserSources as source (source.source_id)}
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
                    customStatusText={`${source.source_type.replaceAll('_', ' ')} · ${source.status.replaceAll('_', ' ')}`}
                    showSkillIcon={false}
                    onFullscreen={source.status === 'connected' ? () => void browseRemoteSource(source) : undefined}
                  >
                    {#snippet details()}
                      <span class="folder-card-contents">
                        <span class="folder-child-row"><span class="folder-child-icon child-folder" aria-hidden="true"></span><span>{$text('projects.connected_source')}</span><small>{typeof source.metadata.root === 'string' ? source.metadata.root : source.source_type.replaceAll('_', ' ')}</small></span>
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
                  <small>{source.source_type.replaceAll('_', ' ')} · {source.status.replaceAll('_', ' ')}</small>
                </button>
              {/if}
            {/each}
        </div>

        {#if activeRemoteSource}
          <div class="remote-browser" data-testid="project-remote-browser">
            <div class="remote-path-row">
              <button
                type="button"
                data-testid="project-remote-parent"
                disabled={remotePath === '.' || isRemoteLoading}
                onclick={() => void browseRemoteSource(activeRemoteSource, remoteParentPath(remotePath))}
              >Up</button>
              <nav class="remote-breadcrumbs" aria-label="Connected source path">
                <button type="button" onclick={() => void browseRemoteSource(activeRemoteSource, '.')}>{activeRemoteSource.displayName || 'Source root'}</button>
                {#each remotePathBreadcrumbs(remotePath) as crumb, index (crumb.path)}
                  <span>/</span>
                  {#if index === remotePathBreadcrumbs(remotePath).length - 1}
                    <code aria-current="page">{crumb.label}</code>
                  {:else}
                    <button type="button" onclick={() => void browseRemoteSource(activeRemoteSource, crumb.path)}>{crumb.label}</button>
                  {/if}
                {/each}
              </nav>
              <button type="button" disabled={isRemoteLoading} onclick={() => void browseRemoteSource(activeRemoteSource, remotePath)}>Refresh</button>
            </div>
            <form class="remote-search" onsubmit={(event) => { event.preventDefault(); void searchRemoteSource(activeRemoteSource); }}>
              <input
                bind:value={remoteSearchQuery}
                data-testid="project-remote-search-input"
                placeholder="Search this source"
                aria-label="Search this remote source"
              />
              <button data-testid="project-remote-search-submit" type="submit" disabled={!remoteSearchQuery.trim() || isRemoteLoading}>Search</button>
            </form>
            {#if remoteError}
              <p class="remote-error" data-testid="project-remote-error">{remoteError}</p>
            {/if}
            {#if remoteOmittedCount > 0}
              <p class="remote-limit-notice" data-testid="project-remote-results-truncated">{$text('projects.remote_results_limited')}</p>
            {/if}
            {#if remoteExcludedCount > 0}
              <p class="muted" data-testid="project-remote-results-protected">{$text('projects.remote_results_protected')}</p>
            {/if}
            {#if isRemoteLoading}
              <p class="muted" data-testid="project-remote-loading">Loading from your device...</p>
            {:else if remoteSearchMatches.length > 0}
              <div class="remote-results remote-search-results" data-testid="project-remote-search-results">
                {#each remoteSearchMatches as match (`${match.path}:${match.line}`)}
                  <button class="remote-result" type="button" onclick={() => void openRemoteFile(activeRemoteSource, match.path)}>
                    <strong>{match.path}</strong>
                    <small>Line {match.line}</small>
                    <span>{match.snippet}</span>
                  </button>
                {/each}
              </div>
            {:else}
              <div class="remote-results" data-testid="project-remote-directory-results">
                {#each remoteEntries as entry (entry.path)}
                  {#if entry.kind === 'directory'}
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
                        customStatusText="Connected folder"
                        showSkillIcon={false}
                        onFullscreen={() => void openRemoteEntry(activeRemoteSource, entry)}
                      >
                        {#snippet details()}
                          <span class="folder-card-contents">
                            <span class="folder-child-row"><span class="folder-child-icon child-folder" aria-hidden="true"></span><span>{entry.path}</span><small>Folder</small></span>
                          </span>
                        {/snippet}
                      </UnifiedEmbedPreview>
                    </div>
                  {:else}
                    {@const previewEntry = remoteEntryPreview(activeRemoteSource, entry)}
                    <div class="remote-file-entry" data-testid="project-remote-entry" data-kind="file">
                      <ProjectRemotePreviewCard
                        preview={previewEntry.preview}
                        sourceLabel={previewEntry.sourceLabel}
                        canUpload={previewEntry.canImport}
                        isUploading={isSaving}
                        previewOnly={viewerSplitOpen}
                        onOpenFullscreen={() => void openRemoteFile(activeRemoteSource, entry.path)}
                        onUpload={() => void handleUploadRemotePreview(previewEntry)}
                      />
                    </div>
                  {/if}
                {/each}
                {#if remoteEntries.length === 0}
                  <p class="muted">No readable entries in this folder.</p>
                {/if}
              </div>
            {/if}
            <div class="source-previews">
              {#each remotePreviewEntries.filter((entry) => entry.preview.embed.content.source_id === activeRemoteSource.source_id
                && !remoteEntries.some((remoteEntry) => remoteEntry.path === entry.preview.embed.content.path)) as previewEntry (previewEntry.preview.embed.embed_id)}
                <ProjectRemotePreviewCard
                  preview={previewEntry.preview}
                  sourceLabel={previewEntry.sourceLabel}
                  canUpload={previewEntry.canImport}
                  isUploading={isSaving}
                  previewOnly={viewerSplitOpen}
                  onOpenFullscreen={() => void openRemotePreview(previewEntry.preview)}
                  onUpload={() => void handleUploadRemotePreview(previewEntry)}
                />
              {/each}
            </div>
          </div>
        {/if}
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
  <div class="projects-workspace-layout" class:viewer-open={!!activeRemoteFullscreen || !!activeStoredFullscreen} bind:clientWidth={workspaceWidth}>
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

    {#if activeRemoteFullscreen || activeStoredFullscreen}
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

  .folders-panel { max-width: 64rem; }
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
    position: relative;
    inset: auto;
    width: 100%;
    margin-bottom: var(--spacing-8);
    transform: none;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

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
    grid-template-columns: repeat(auto-fill, minmax(min(16rem, 100%), 1fr));
    gap: 16px;
  }

  .browser-list {
    display: grid;
    gap: 8px;
  }

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

  .project-breadcrumbs,
  .remote-breadcrumbs {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: var(--spacing-2);
    overflow: hidden;
  }

  .breadcrumb-button {
    margin-top: 8px;
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
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(18.75rem, 100%), 18.75rem));
    gap: 14px;
  }

  .remote-browser {
    display: grid;
    gap: var(--spacing-8);
    margin-top: var(--spacing-8);
    padding: var(--spacing-8);
    border-radius: var(--radius-5);
    background: var(--color-grey-10);
  }

  .remote-path-row,
  .remote-search {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
  }

  .remote-breadcrumbs {
    flex: 1;
  }

  .remote-results {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(18.75rem, 100%), 18.75rem));
    align-items: start;
    gap: var(--spacing-4);
  }

  .remote-search-results {
    grid-template-columns: 1fr;
  }

  .remote-result {
    display: grid;
    gap: var(--spacing-2);
    width: 100%;
    color: var(--color-font-primary);
    text-align: start;
    background: var(--color-grey-0);
    border: 1px solid var(--color-grey-25);
  }

  .remote-file-entry {
    width: min(18.75rem, 100%);
    min-width: 0;
  }

  .remote-file-entry :global(.remote-preview-card) {
    width: 100%;
  }

  .remote-result small {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }

  .remote-result span {
    overflow: hidden;
    color: var(--color-font-secondary);
    font-family: monospace;
    text-overflow: ellipsis;
    white-space: nowrap;
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

  @container project-page (max-width: 500px) {
    .project-panel {
      width: calc(100% - var(--spacing-4));
      padding-inline: var(--spacing-5);
    }

    .folder-summary-row {
      grid-template-columns: 1fr auto;
      gap: var(--spacing-4);
    }

    .folder-search {
      grid-column: 1 / -1;
      grid-row: 2;
    }

    .browser-grid,
    .remote-results,
    .source-previews {
      grid-template-columns: minmax(0, 1fr);
    }

    .remote-browser {
      padding: var(--spacing-4);
    }

    .remote-path-row {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      gap: var(--spacing-2);
    }

    .remote-breadcrumbs {
      min-width: 0;
      overflow: hidden;
    }

    .remote-breadcrumbs button,
    .remote-breadcrumbs code {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .remote-search {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: var(--spacing-2);
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
    .create-menu.folder-create-menu { grid-template-columns: 1fr; }
    .create-menu.folder-create-menu button + button { border-inline-start: 0; border-top: 1px solid var(--color-grey-25); }

    .remote-path-row,
    .remote-search {
      align-items: stretch;
      flex-wrap: wrap;
    }

    .remote-breadcrumbs {
      flex-basis: 100%;
    }
  }
</style>
