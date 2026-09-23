<!--
  ProjectsPage.svelte
  Projects V1 workspace UI for manually organizing chats, embeds, and uploads.
  Files uploaded here are converted into embeds first and then linked through
  project_items, so project storage follows the same encryption/rendering model
  as the rest of OpenMates.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '@repo/ui';
  import CodeEmbedFullscreen from '../embeds/code/CodeEmbedFullscreen.svelte';
  import ProjectBrowserItem from './ProjectBrowserItem.svelte';
  import ProjectRemotePreviewCard from './ProjectRemotePreviewCard.svelte';
  import TasksPage from '../tasks/TasksPage.svelte';
  import WorkspaceDetailHeader from '../workspace/WorkspaceDetailHeader.svelte';
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
  import {
    createFolder,
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

  const PROJECTS_ROUTE = '/projects';
  const PROJECT_ID_HASH_PARAM = 'project-id';

  let { variant = 'main' }: { variant?: 'main' | 'sidebar' } = $props();

  let projects = $state<ProjectViewModel[]>([]);
  let selectedProject = $state<ProjectViewModel | null>(null);
  let folders = $state<ProjectFolderViewModel[]>([]);
  let items = $state<ProjectItemViewModel[]>([]);
  let sources = $state<ProjectSourceViewModel[]>([]);
  let isLoading = $state(true);
  let isSaving = $state(false);
  let newProjectName = $state('');
  let newProjectWriteMode = $state<ProjectWriteMode | null>(null);
  let newFolderName = $state('');
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
    params.delete(PROJECT_ID_HASH_PARAM);
    if (projectId) params.set(PROJECT_ID_HASH_PARAM, projectId);
    return serializeHashParams(params);
  }

  function projectStateHref(projectId: string): string {
    return `${PROJECTS_ROUTE}${projectStateHash(projectId)}`;
  }

  function setProjectUrlState(projectId: string | null): void {
    const nextHash = projectStateHash(projectId, window.location.hash);
    projectHashId = readProjectHashId(nextHash);
    window.history.replaceState(window.history.state, '', `${PROJECTS_ROUTE}${nextHash}`);
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
      resetRemoteBrowser();
      return;
    }
    const [contents, projectSources] = await Promise.all([
      getProjectContents(selectedProject),
      listProjectSources(selectedProject),
    ]);
    folders = contents.folders;
    items = contents.items;
    sources = projectSources;
    folderHashes = new Map(await Promise.all(contents.folders.map(async (folder) => [folder.folder_id, await computeSHA256(folder.folder_id)] as const)));
    if (currentFolder && !contents.folders.some((folder) => folder.folder_id === currentFolder?.folder_id)) {
      currentFolder = null;
      currentFolderTrail = [];
      currentFolderHash = null;
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
    resetRemoteBrowser();
  }

  async function selectProject(project: ProjectViewModel, updateHash = true): Promise<void> {
    selectedProject = project;
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
        setProjectUrlState(null);
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

  async function handleCreateProject(): Promise<void> {
    const name = newProjectName.trim();
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

  async function handleCreateFolder(): Promise<void> {
    if (!selectedProject) return;
    const name = newFolderName.trim();
    if (!name || isSaving) return;
    isSaving = true;
    try {
      await createFolder(selectedProject, name, currentFolder?.folder_id);
      newFolderName = '';
      await refreshSelectedProject();
      notificationStore.success('Folder created');
    } catch (error) {
      console.error('[ProjectsPage] Failed to create folder:', error);
      notificationStore.error('Failed to create folder');
    } finally {
      isSaving = false;
    }
  }

  async function handleUploadSelected(event: Event): Promise<void> {
    if (!selectedProject) return;
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    isSaving = true;
    try {
      await uploadFileToProject(selectedProject, file);
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
      await uploadFileToProject(project, candidate.file, candidate.metadata);
      await refreshSelectedProject();
      notificationStore.success('Remote file uploaded to OpenMates');
    } catch (error) {
      console.error('[ProjectsPage] Failed to upload remote preview to project:', error);
      notificationStore.error('Failed to upload remote file');
    } finally {
      isSaving = false;
    }
  }

  async function openRemotePreview(preview: VirtualRemoteFilePreview): Promise<void> {
    const entry = remotePreviewEntries.find((candidate) => candidate.preview.embed.embed_id === preview.embed.embed_id);
    if (entry?.readResult) {
      activeRemoteFullscreen = buildVirtualRemoteFullscreenDetail(preview, entry.readResult.content);
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
    if (!selectedProject || !$userProfile.user_id) return;
    activeRemoteSourceId = source.source_id;
    activeRemoteFullscreen = null;
    remotePreviewEntries = [];
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
    if (!selectedProject || !$userProfile.user_id) return;
    const classification = classifyRemotePreviewPath(path);
    if (classification.kind === 'unsupported') {
      remoteError = $text('projects.remote_preview_unsupported');
      return;
    }
    activeRemoteSourceId = source.source_id;
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
      activeRemoteFullscreen = buildVirtualRemoteFullscreenDetail(preview, result.content);
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
    return {
      preview: normalizeRemoteFilePreview({
        sourceId: source.source_id,
        path: entry.path,
        displayName: entry.path.split('/').filter(Boolean).pop() || entry.path,
        language: classification.kind === 'unsupported' ? 'text' : classification.language,
        snippet: '',
        snippetTruncated: false,
        previewPolicy: 'bounded_full_text',
        safetyFlags: [],
      }),
      readResult: null,
      canImport: false,
      sourceLabel: source.displayName || source.source_id,
    };
  }

  async function openFolder(folder: ProjectFolderViewModel): Promise<void> {
    currentVirtualPath = null;
    currentFolder = folder;
    currentFolderHash = folderHashes.get(folder.folder_id) ?? await computeSHA256(folder.folder_id);
    const trail: ProjectFolderViewModel[] = [];
    let cursor: ProjectFolderViewModel | undefined = folder;
    const visited = new Set<string>();
    while (cursor && !visited.has(cursor.folder_id)) {
      visited.add(cursor.folder_id);
      trail.unshift(cursor);
      const parentHash = cursor.parentHash;
      cursor = parentHash
        ? folders.find((candidate) => folderHashes.get(candidate.folder_id) === parentHash)
        : undefined;
    }
    currentFolderTrail = trail;
  }

  function openVirtualFolder(folder: ProjectVirtualFolder): void {
    currentFolder = null;
    currentFolderTrail = [];
    currentFolderHash = null;
    currentVirtualPath = folder.path;
  }

  function openRoot(): void {
    currentFolder = null;
    currentFolderTrail = [];
    currentFolderHash = null;
    currentVirtualPath = null;
  }

  async function loadProjectEmbed(item: ProjectItemViewModel): Promise<{
    embedData: Record<string, unknown>;
    decodedContent: Record<string, unknown>;
  } | null> {
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

  onMount(() => {
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
    window.addEventListener(PROJECT_SELECTED_EVENT, handleProjectSelected);
    window.addEventListener(PROJECTS_CHANGED_EVENT, handleProjectsChanged);
    return () => {
      remoteRequestController?.abort();
      window.removeEventListener('hashchange', syncProjectHashFromLocation);
      window.removeEventListener(PROJECT_SELECTED_EVENT, handleProjectSelected);
      window.removeEventListener(PROJECTS_CHANGED_EVENT, handleProjectsChanged);
      window.clearInterval(sourceStatusTimer);
    };
  });

  $effect(() => {
    if (variant !== 'main' || isLoading) return;
    if (!projectHashId) {
      if (selectedProject) clearSelectedProject();
      return;
    }
    if (selectedProject?.project_id === projectHashId) return;
    void selectProjectById(projectHashId, false);
  });
</script>

{#snippet createProjectForm(compact = false)}
  <form class="create-row" class:compact onsubmit={(event) => { event.preventDefault(); void handleCreateProject(); }}>
    <input
      data-testid="project-name-input"
      bind:value={newProjectName}
      placeholder="New project name"
      aria-label="New project name"
    />
    {@render writePolicyChoice()}
    <button data-testid="project-create-button" type="submit" disabled={isSaving || !newProjectName.trim() || !newProjectWriteMode}>
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
            <span>{project.name || 'Untitled project'}</span>
            <small>{project.encrypted.item_count ?? 0} items</small>
          </button>
          <a href={projectStateHref(project.project_id)} data-testid="project-detail-link" onclick={(event) => { event.preventDefault(); void selectProject(project); }}>Open</a>
        </article>
      {/each}
    </div>
  {/if}
{/snippet}

{#snippet selectedProjectDetails()}
  {#if selectedProject}
      <header class="project-detail-topbar">
        <button type="button" class="back-action" data-testid="project-detail-back" onclick={openProjectsHome} aria-label="Back to projects">
          &larr;
        </button>
        <div class="header-actions">
          <button type="button" onclick={() => uploadInput?.click()} disabled={isSaving} data-testid="project-upload-button">
            Upload file
          </button>
          <button class="settings-gear-button" type="button" data-testid="project-settings-button" aria-label="Open project settings" onclick={openSelectedProjectSettings}>
            Settings
          </button>
          <button type="button" class="destructive-action" onclick={() => void handleDeleteProject(selectedProject as ProjectViewModel)} data-testid="project-delete-button">
            Delete
          </button>
          <input bind:this={uploadInput} type="file" onchange={handleUploadSelected} hidden />
        </div>
      </header>

      <WorkspaceDetailHeader
        title={selectedProject.name || 'Untitled project'}
        description={selectedProject.description || 'Add chats, embeds, PDFs, sheets, images, audio, video, code, mail, and files.'}
        category="productivity"
        icon="folder"
        writable={true}
        onSaveTitle={saveSelectedProjectTitle}
        onSaveDescription={saveSelectedProjectDescription}
        metadata={`${selectedProject.encrypted.item_count ?? 0} items`}
      />

      <section class="project-section">
        <div class="section-title">
          <div>
            <h3>{currentVirtualPath?.split('/').at(-1) || (currentFolder ? currentFolder.name || 'Untitled folder' : 'Project files')}</h3>
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
          {#if currentVirtualPath === null}
            <form class="create-row compact" onsubmit={(event) => { event.preventDefault(); void handleCreateFolder(); }}>
              <input bind:value={newFolderName} placeholder="New folder" aria-label="New folder" data-testid="project-folder-name-input" />
              <button type="submit" disabled={isSaving || !newFolderName.trim()} data-testid="project-folder-create-button">Add folder</button>
            </form>
          {/if}
        </div>

        <div class="browser-toolbar">
          <span class="muted">{browserFolders.length + browserVirtualFolders.length + browserItems.length + browserSources.length} entries</span>
          <div class="view-toggle" aria-label="Project view mode">
            <button type="button" class:active={viewMode === 'tile'} onclick={() => (viewMode = 'tile')}>Tile</button>
            <button type="button" class:active={viewMode === 'list'} onclick={() => (viewMode = 'list')}>List</button>
          </div>
        </div>

        {#if browserFolders.length === 0 && browserVirtualFolders.length === 0 && browserItems.length === 0 && browserSources.length === 0}
          <div class="empty-state" data-testid="project-empty-items">
            <h3>No project items yet</h3>
            <p>Upload a file or use “Add to project” from chats and embed fullscreen views.</p>
          </div>
        {:else}
          <div class:browser-grid={viewMode === 'tile'} class:browser-list={viewMode === 'list'} data-testid="project-browser-list">
            {#each browserFolders as folder (folder.folder_id)}
              <button class="folder-entry {viewMode}" data-testid="project-folder-card" type="button" onclick={() => void openFolder(folder)}>
                <span class="folder-icon">Folder</span>
                <strong>{folder.name || 'Untitled folder'}</strong>
                <small>Folder</small>
              </button>
            {/each}
            {#each browserVirtualFolders as folder (folder.path)}
              <button class="folder-entry {viewMode}" data-testid="project-virtual-folder-card" type="button" onclick={() => openVirtualFolder(folder)}>
                <span class="folder-icon">Folder</span>
                <strong>{folder.name}</strong>
                <small>Hosted path</small>
              </button>
            {/each}
            {#each browserItems as item (item.project_item_id)}
              <ProjectBrowserItem
                {item}
                {viewMode}
                displayName={projectBrowserItemName(item)}
                loadProjectEmbed={loadProjectEmbed}
                onOpenFullscreen={openStoredFullscreen}
              />
            {/each}
            {#each browserSources as source (source.source_id)}
              <button
                class="source-root-entry {viewMode}"
                data-testid="project-connected-source-root"
                data-status={source.status}
                type="button"
                disabled={source.status !== 'connected'}
                onclick={() => void browseRemoteSource(source)}
              >
                <span class="source-root-icon">{$text('projects.connected_source')}</span>
                <strong>{source.displayName || source.source_id}</strong>
                <small>{source.source_type.replaceAll('_', ' ')} · {source.status.replaceAll('_', ' ')}</small>
              </button>
            {/each}
          </div>
        {/if}
      </section>

      <section class="project-section" data-testid="project-remote-sources-section">
        <div class="section-title">
          <div>
            <h3>Remote sources</h3>
            <p class="muted">Connected folders and repositories stay on your machine unless you upload selected files.</p>
          </div>
        </div>
        {#if sources.length === 0}
          <div class="empty-state compact" data-testid="project-remote-sources-empty">
            <h3>No remote sources connected</h3>
            <p>Use the OpenMates CLI remote-access bridge to attach a folder or repository.</p>
          </div>
        {:else}
          <div class="source-list" data-testid="project-remote-sources-list">
            {#each sources as source (source.source_id)}
              <article class="source-card" data-testid="project-remote-source-card" data-status={source.status}>
                <div class="source-card-header">
                  <div class="source-summary">
                    <span class="source-kind">{source.source_type.replaceAll('_', ' ')}</span>
                    <strong>{source.displayName || source.source_id}</strong>
                    {#if typeof source.metadata.root === 'string'}
                      <small>{source.metadata.root}</small>
                    {/if}
                  </div>
                  <span class="source-status">{source.status.replaceAll('_', ' ')}</span>
                </div>
                <button
                  class="source-browse-button"
                  type="button"
                  data-testid="project-remote-source-browse"
                  disabled={source.status !== 'connected' || isRemoteLoading}
                  onclick={() => void browseRemoteSource(source)}
                >
                  {source.status === 'connected' ? 'Browse source' : 'Source offline'}
                </button>
                {#if activeRemoteSourceId === source.source_id}
                  <div class="remote-browser" data-testid="project-remote-browser">
                    <div class="remote-path-row">
                      <button
                        type="button"
                        data-testid="project-remote-parent"
                        disabled={remotePath === '.' || isRemoteLoading}
                        onclick={() => void browseRemoteSource(source, remoteParentPath(remotePath))}
                      >Up</button>
                      <nav class="remote-breadcrumbs" aria-label="Connected source path">
                        <button type="button" onclick={() => void browseRemoteSource(source, '.')}>{source.displayName || 'Source root'}</button>
                        {#each remotePathBreadcrumbs(remotePath) as crumb, index (crumb.path)}
                          <span>/</span>
                          {#if index === remotePathBreadcrumbs(remotePath).length - 1}
                            <code aria-current="page">{crumb.label}</code>
                          {:else}
                            <button type="button" onclick={() => void browseRemoteSource(source, crumb.path)}>{crumb.label}</button>
                          {/if}
                        {/each}
                      </nav>
                      <button type="button" disabled={isRemoteLoading} onclick={() => void browseRemoteSource(source, remotePath)}>Refresh</button>
                    </div>
                    <form class="remote-search" onsubmit={(event) => { event.preventDefault(); void searchRemoteSource(source); }}>
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
                      <div class="remote-results" data-testid="project-remote-search-results">
                        {#each remoteSearchMatches as match (`${match.path}:${match.line}`)}
                          <button class="remote-result" type="button" onclick={() => void openRemoteFile(source, match.path)}>
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
                            <button
                              class="remote-entry"
                              type="button"
                              data-testid="project-remote-entry"
                              data-kind={entry.kind}
                              onclick={() => void openRemoteEntry(source, entry)}
                            >
                              <span>Folder</span>
                              <strong>{entry.path.split('/').filter(Boolean).pop() || entry.path}</strong>
                            </button>
                          {:else}
                            {@const previewEntry = remoteEntryPreview(source, entry)}
                            <div class="remote-file-entry" data-testid="project-remote-entry" data-kind="file">
                              <ProjectRemotePreviewCard
                                preview={previewEntry.preview}
                                sourceLabel={previewEntry.sourceLabel}
                                canUpload={previewEntry.canImport}
                                isUploading={isSaving}
                                onOpenFullscreen={() => void openRemoteFile(source, entry.path)}
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
                  </div>
                {/if}
                <div class="source-previews">
                  {#each remotePreviewEntries.filter((entry) => entry.preview.embed.content.source_id === source.source_id
                    && !remoteEntries.some((remoteEntry) => remoteEntry.path === entry.preview.embed.content.path)) as previewEntry (previewEntry.preview.embed.embed_id)}
                    <ProjectRemotePreviewCard
                      preview={previewEntry.preview}
                      sourceLabel={previewEntry.sourceLabel}
                      canUpload={previewEntry.canImport}
                      isUploading={isSaving}
                      onOpenFullscreen={() => void openRemotePreview(previewEntry.preview)}
                      onUpload={() => void handleUploadRemotePreview(previewEntry)}
                    />
                  {/each}
                </div>
              </article>
            {/each}
          </div>
        {/if}
      </section>

      <section class="project-section" data-testid="project-tasks-section">
        <div class="section-title">
          <div>
            <h3>Project tasks</h3>
            <p class="muted">Plan work for this project and hand focused next steps to AI.</p>
          </div>
        </div>
        {#key selectedProject.project_id}
          <TasksPage projectId={selectedProject.project_id} compact />
        {/key}
      </section>
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
  <section class="projects-page" data-testid="projects-page">
    {#if selectedProject}
      <main class="project-main" data-testid="project-management">
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
          <div class="project-create-controls">
            {@render writePolicyChoice()}
            <WorkspacePromptComposer
              surface="projects"
              bind:value={newProjectName}
              placeholder="Name a new project"
              submitLabel="Create project"
              submittingLabel="Creating..."
              disabled={isSaving || !newProjectWriteMode}
              submitting={isSaving}
              testId="project-input-composer"
              inputTestId="project-input-textarea"
              submitTestId="project-input-submit"
              micTestId="project-input-mic"
              onSubmit={handleCreateProject}
              onMicClick={showProjectVoiceInputUnavailable}
            />
          </div>
        </svelte:fragment>
      </WorkspaceHomeShell>
    {/if}
  </section>
{/if}

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
{/if}

{#if activeStoredFullscreen}
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

<svelte:window onkeydown={handleRemoteFullscreenKeydown} />

<style>
  .projects-page {
    position: relative;
    flex: 1;
    min-width: 0;
    height: 100%;
    overflow: hidden;
    border-radius: 17px;
    background: var(--color-grey-20);
    box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
    color: var(--color-font-primary);
  }

  /* The Project policy selector makes this composer taller than the shared
     prompt-only composer. Dock it in layout so it cannot cover Project cards. */
  .projects-page :global(.workspace-home-shell[data-surface='projects']) {
    display: flex;
    flex-direction: column;
  }

  .projects-page :global(.workspace-home-shell[data-surface='projects'] .workspace-scroll-layer) {
    flex: 1 1 auto;
    height: auto;
  }

  .projects-page :global(.workspace-home-shell[data-surface='projects'] .workspace-composer-slot) {
    position: relative;
    inset: auto;
    flex: 0 0 auto;
    transform: none;
  }

  .project-create-controls {
    display: grid;
    grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.2fr);
    align-items: center;
    gap: var(--spacing-4);
    width: min(100%, 1080px);
  }

  .project-create-controls .write-policy-choice {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
    box-sizing: border-box;
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
    justify-content: space-between;
    background: transparent;
    color: inherit;
    text-align: left;
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
    padding: clamp(14px, 3vw, 32px);
    max-width: 1500px;
    margin: 0 auto;
    box-sizing: border-box;
  }

  .section-title {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--spacing-8);
    margin-bottom: 24px;
  }

  .project-detail-topbar {
    position: sticky;
    top: 0;
    z-index: var(--z-index-raised-3);
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--spacing-6);
    margin-bottom: var(--spacing-5);
    padding: var(--spacing-3) 0;
    background: color-mix(in srgb, var(--color-grey-20) 92%, transparent);
    backdrop-filter: blur(16px);
  }

  .back-action {
    display: grid;
    width: 42px;
    height: 42px;
    place-items: center;
    border-radius: var(--radius-full);
    color: var(--color-font-primary);
    background: var(--color-grey-0);
    font-size: 1.4rem;
    font-weight: 900;
  }

  .header-actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 8px;
  }

  .project-section {
    margin-top: 32px;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 14px;
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
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
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
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: linear-gradient(135deg, var(--color-grey-0), var(--color-grey-10));
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
  }

  .folder-entry.tile,
  .source-root-entry.tile {
    min-height: 210px;
    display: grid;
    align-content: end;
    gap: 8px;
    padding: 18px;
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

  .tile,
  .empty-state {
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    padding: 18px;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
  }

  .project-tile {
    color: inherit;
    text-align: left;
  }

  .tile {
    display: grid;
    gap: 8px;
    min-height: 110px;
  }

  .folder {
    background: linear-gradient(135deg, var(--color-grey-0), var(--color-grey-10));
  }

  .empty-state.large {
    max-width: 520px;
    margin: 12vh auto;
    text-align: center;
  }

  .empty-state.compact {
    box-shadow: none;
  }

  .settings-gear-button {
    background: var(--color-grey-10);
    color: var(--color-font-primary);
  }

  .destructive-action {
    background: var(--color-danger, #b42318);
  }

  .source-list {
    display: grid;
    gap: 10px;
  }

  .source-card {
    display: grid;
    gap: 16px;
    padding: 14px 16px;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
  }

  .source-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }

  .source-summary {
    display: grid;
    gap: 4px;
  }

  .source-previews {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 14px;
  }

  .source-browse-button {
    justify-self: start;
  }

  .remote-browser {
    display: grid;
    gap: var(--spacing-8);
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

  .remote-path-row code {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    color: var(--color-font-secondary);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .remote-breadcrumbs {
    flex: 1;
  }

  .remote-breadcrumbs button {
    flex: 0 1 auto;
    min-width: 0;
    overflow: hidden;
    padding: 0;
    color: var(--color-font-secondary);
    text-overflow: ellipsis;
    white-space: nowrap;
    background: transparent;
  }

  .remote-breadcrumbs code {
    flex: 0 1 auto;
  }

  .remote-search input {
    background: var(--color-grey-0);
  }

  .remote-results {
    display: grid;
    gap: var(--spacing-4);
  }

  .remote-entry,
  .remote-result {
    display: grid;
    gap: var(--spacing-2);
    width: 100%;
    color: var(--color-font-primary);
    text-align: start;
    background: var(--color-grey-0);
    border: 1px solid var(--color-grey-25);
  }

  .remote-entry {
    grid-template-columns: auto 1fr;
    align-items: center;
  }

  .remote-file-entry {
    min-width: 0;
  }

  .remote-file-entry :global(.remote-preview-card) {
    width: 100%;
  }

  .remote-entry span,
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

  .source-kind,
  .source-status {
    color: var(--color-font-secondary);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .source-status {
    padding: 5px 8px;
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
  }

  .projects-remote-fullscreen {
    position: fixed;
    inset: 0;
    z-index: var(--z-index-popover);
    background: var(--color-grey-0);
  }

  .load-error {
    margin: 0 15px;
    color: var(--color-font-secondary);
  }

  @media (max-width: 800px) {
    .project-create-controls,
    .project-create-controls .write-policy-choice {
      grid-template-columns: 1fr;
    }

    .section-title,
    .project-detail-topbar {
      flex-direction: column;
      align-items: stretch;
    }

    .project-detail-topbar {
      position: static;
    }

    .browser-grid {
      grid-template-columns: 1fr;
    }

    .remote-path-row,
    .remote-search {
      align-items: stretch;
      flex-wrap: wrap;
    }

    .remote-path-row code,
    .remote-breadcrumbs,
    .remote-search input {
      flex-basis: 100%;
    }
  }
</style>
