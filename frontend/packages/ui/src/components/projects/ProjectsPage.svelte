<!--
  ProjectsPage.svelte
  Projects V1 workspace UI for manually organizing chats, embeds, and uploads.
  Files uploaded here are converted into embeds first and then linked through
  project_items, so project storage follows the same encryption/rendering model
  as the rest of OpenMates.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import CodeEmbedFullscreen from '../embeds/code/CodeEmbedFullscreen.svelte';
  import ProjectBrowserItem from './ProjectBrowserItem.svelte';
  import ProjectRemotePreviewCard from './ProjectRemotePreviewCard.svelte';
  import TasksPage from '../tasks/TasksPage.svelte';
  import WorkspaceDetailHeader from '../workspace/WorkspaceDetailHeader.svelte';
  import WorkspaceHomeShell from '../workspace/WorkspaceHomeShell.svelte';
  import WorkspacePromptComposer from '../workspace/WorkspacePromptComposer.svelte';
  import WorkspaceReportIssueButton from '../workspace/WorkspaceReportIssueButton.svelte';
  import { notificationStore } from '../../stores/notificationStore';
  import { panelState } from '../../stores/panelStateStore';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { userProfile } from '../../stores/userProfile';
  import { computeSHA256 } from '../../message_parsing/utils';
  import {
    createFolder,
    createProject,
    deleteProject,
    getProject,
    getProjectContents,
    listProjectSources,
    listProjects,
    updateProjectMetadata,
    uploadFileToProject,
    type ProjectFolderViewModel,
    type ProjectItemViewModel,
    type ProjectSourceViewModel,
    type ProjectViewModel,
  } from '../../services/projectService';
  import {
    buildRemoteFileUploadCandidate,
    buildVirtualRemoteFullscreenDetail,
    normalizeRemoteFilePreview,
    type VirtualRemoteFullscreenDetail,
    type VirtualRemoteFilePreview,
  } from '../../services/projectRemoteSources';

  interface RemotePreviewEntry {
    preview: VirtualRemoteFilePreview;
    uploadContent: string | Blob | null;
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
  let newFolderName = $state('');
  let uploadInput = $state<HTMLInputElement>();
  let hasLoadError = $state(false);
  let viewMode = $state<'tile' | 'list'>('tile');
  let currentFolder = $state<ProjectFolderViewModel | null>(null);
  let currentFolderHash = $state<string | null>(null);
  let folderHashes = $state(new Map<string, string>());
  let activeRemoteFullscreen = $state<VirtualRemoteFullscreenDetail | null>(null);
  let projectHashId = $state<string | null>(null);

  let sortedProjects = $derived([...projects].sort((a, b) => (b.encrypted.created_at || 0) - (a.encrypted.created_at || 0)));
  let recentProjects = $derived(sortedProjects.slice(0, 8));
  let greetingName = $derived($userProfile.username || 'there');
  let browserFolders = $derived(folders.filter((folder) => (folder.parentHash ?? null) === currentFolderHash));
  let browserItems = $derived(items.filter((item) => (item.encrypted.hashed_folder_id ?? null) === currentFolderHash));
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
  const PROJECTS_CHANGED_EVENT = 'openmates-projects-changed';

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

  function broadcastProjectsChanged(): void {
    window.dispatchEvent(new CustomEvent(PROJECTS_CHANGED_EVENT));
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
      currentFolderHash = null;
      folderHashes = new Map();
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
      currentFolderHash = null;
    }
  }

  function clearSelectedProject(): void {
    selectedProject = null;
    folders = [];
    items = [];
    sources = [];
    currentFolder = null;
    currentFolderHash = null;
    folderHashes = new Map();
  }

  async function selectProject(project: ProjectViewModel, updateHash = true): Promise<void> {
    selectedProject = project;
    currentFolder = null;
    currentFolderHash = null;
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
    if (!name || isSaving) return;
    isSaving = true;
    try {
      const project = await createProject(name);
      projects = [project, ...projects];
      selectedProject = project;
      currentFolder = null;
      currentFolderHash = null;
      folders = [];
      items = [];
      sources = [];
      newProjectName = '';
      setProjectUrlState(project.project_id);
      broadcastProjectsChanged();
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
      broadcastProjectsChanged();
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
    broadcastProjectsChanged();
  }

  async function saveSelectedProjectDescription(description: string): Promise<void> {
    if (!selectedProject) return;
    const updatedProject = await updateProjectMetadata(selectedProject, { description });
    selectedProject = updatedProject;
    updateProjectInList(updatedProject);
    broadcastProjectsChanged();
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
    if (!selectedProject || !entry.uploadContent || isSaving) return;
    isSaving = true;
    try {
      const candidate = buildRemoteFileUploadCandidate({
        preview: entry.preview,
        content: entry.uploadContent,
      });
      await uploadFileToProject(selectedProject, candidate.file, candidate.metadata);
      await refreshSelectedProject();
      notificationStore.success('Remote file uploaded to OpenMates');
    } catch (error) {
      console.error('[ProjectsPage] Failed to upload remote preview to project:', error);
      notificationStore.error('Failed to upload remote file');
    } finally {
      isSaving = false;
    }
  }

  function openRemotePreview(preview: VirtualRemoteFilePreview): void {
    activeRemoteFullscreen = buildVirtualRemoteFullscreenDetail(preview);
  }

  function closeRemotePreview(): void {
    activeRemoteFullscreen = null;
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

  function getRemotePreviewEntries(source: ProjectSourceViewModel): RemotePreviewEntry[] {
    const candidates = getRemotePreviewCandidates(source.metadata);
    return candidates.flatMap((candidate) => {
      try {
        const preview = normalizeRemoteFilePreview({
          sourceId: source.source_id,
          path: getString(candidate, 'path') || getString(candidate, 'remote_path'),
          displayName: getString(candidate, 'displayName') || getString(candidate, 'display_name') || getString(candidate, 'path') || source.displayName || source.source_id,
          remoteItemId: getString(candidate, 'remoteItemId') || getString(candidate, 'remote_item_id'),
          kind: getPreviewKind(candidate),
          language: getString(candidate, 'language') || 'text',
          snippet: getString(candidate, 'snippet'),
          baseHash: getString(candidate, 'baseHash') || getString(candidate, 'base_hash'),
          sizeBytes: getNumber(candidate, 'sizeBytes') ?? getNumber(candidate, 'size_bytes'),
          lineCount: getNumber(candidate, 'lineCount') ?? getNumber(candidate, 'line_count'),
          mtime: getString(candidate, 'mtime'),
          contentHash: getString(candidate, 'contentHash') || getString(candidate, 'content_hash'),
          gitStatus: getString(candidate, 'gitStatus') || getString(candidate, 'git_status'),
          previewPolicy: getString(candidate, 'previewPolicy') || getString(candidate, 'preview_policy'),
          safetyFlags: getStringArray(candidate, 'safetyFlags') ?? getStringArray(candidate, 'safety_flags') ?? [],
        });
        return [{
          preview,
          uploadContent: getUploadContent(candidate),
          sourceLabel: source.displayName || source.source_id,
        }];
      } catch (error) {
        console.warn('[ProjectsPage] Ignoring invalid remote preview metadata:', error);
        return [];
      }
    });
  }

  function getRemotePreviewCandidates(metadata: Record<string, unknown>): Record<string, unknown>[] {
    const previewFiles = metadata.preview_files ?? metadata.previewFiles ?? metadata.remote_previews;
    if (Array.isArray(previewFiles)) return previewFiles.filter(isRecord);
    const preview = metadata.preview ?? metadata.remote_preview;
    return isRecord(preview) ? [preview] : [];
  }

  function getPreviewKind(candidate: Record<string, unknown>): 'file' | 'folder' {
    return getString(candidate, 'kind') === 'folder' ? 'folder' : 'file';
  }

  function getUploadContent(candidate: Record<string, unknown>): string | Blob | null {
    const content = candidate.full_content ?? candidate.fullContent ?? candidate.content;
    if (typeof content === 'string') return content;
    if (typeof Blob !== 'undefined' && content instanceof Blob) return content;
    return null;
  }

  function isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  function getString(candidate: Record<string, unknown>, key: string): string {
    const value = candidate[key];
    return typeof value === 'string' ? value : '';
  }

  function getNumber(candidate: Record<string, unknown>, key: string): number | undefined {
    const value = candidate[key];
    return Number.isInteger(value) && Number(value) >= 0 ? Number(value) : undefined;
  }

  function getStringArray(candidate: Record<string, unknown>, key: string): string[] | undefined {
    const value = candidate[key];
    return Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : undefined;
  }

  async function openFolder(folder: ProjectFolderViewModel): Promise<void> {
    currentFolder = folder;
    currentFolderHash = folderHashes.get(folder.folder_id) ?? await computeSHA256(folder.folder_id);
  }

  function openRoot(): void {
    currentFolder = null;
    currentFolderHash = null;
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
      currentFolderHash = null;
      if (variant === 'main') setProjectUrlState(project.project_id);
      void refreshSelectedProject();
    };
    const handleProjectsChanged = () => {
      void refreshProjects();
    };
    window.addEventListener('hashchange', syncProjectHashFromLocation);
    window.addEventListener(PROJECT_SELECTED_EVENT, handleProjectSelected);
    window.addEventListener(PROJECTS_CHANGED_EVENT, handleProjectsChanged);
    return () => {
      window.removeEventListener('hashchange', syncProjectHashFromLocation);
      window.removeEventListener(PROJECT_SELECTED_EVENT, handleProjectSelected);
      window.removeEventListener(PROJECTS_CHANGED_EVENT, handleProjectsChanged);
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
    <button data-testid="project-create-button" type="submit" disabled={isSaving || !newProjectName.trim()}>
      Create project
    </button>
  </form>
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
            <h3>{currentFolder ? currentFolder.name || 'Untitled folder' : 'Project files'}</h3>
            <button class="breadcrumb-button" type="button" onclick={openRoot}>All projects</button>
            {#if currentFolder}
              <span class="breadcrumb-separator">/</span>
              <span class="breadcrumb-current">{currentFolder.name || 'Untitled folder'}</span>
            {/if}
          </div>
          <form class="create-row compact" onsubmit={(event) => { event.preventDefault(); void handleCreateFolder(); }}>
            <input bind:value={newFolderName} placeholder="New folder" aria-label="New folder" data-testid="project-folder-name-input" />
            <button type="submit" disabled={isSaving || !newFolderName.trim()} data-testid="project-folder-create-button">Add folder</button>
          </form>
        </div>

        <div class="browser-toolbar">
          <span class="muted">{browserFolders.length + browserItems.length} entries</span>
          <div class="view-toggle" aria-label="Project view mode">
            <button type="button" class:active={viewMode === 'tile'} onclick={() => (viewMode = 'tile')}>Tile</button>
            <button type="button" class:active={viewMode === 'list'} onclick={() => (viewMode = 'list')}>List</button>
          </div>
        </div>

        {#if browserFolders.length === 0 && browserItems.length === 0}
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
            {#each browserItems as item (item.project_item_id)}
              <ProjectBrowserItem {item} {viewMode} />
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
                <div class="source-previews">
                  {#each getRemotePreviewEntries(source) as previewEntry (previewEntry.preview.embed.embed_id)}
                    <ProjectRemotePreviewCard
                      preview={previewEntry.preview}
                      sourceLabel={previewEntry.sourceLabel}
                      canUpload={!!previewEntry.uploadContent}
                      isUploading={isSaving}
                      onOpenFullscreen={() => openRemotePreview(previewEntry.preview)}
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
    <div class="workspace-report-action"><WorkspaceReportIssueButton /></div>
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
            onSubmit={handleCreateProject}
            onMicClick={showProjectVoiceInputUnavailable}
          />
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

  .workspace-report-action {
    position: absolute;
    z-index: var(--z-index-raised-3);
    top: var(--spacing-5);
    right: var(--spacing-5);
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

  .folder-entry {
    color: inherit;
    text-align: left;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: linear-gradient(135deg, var(--color-grey-0), var(--color-grey-10));
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
  }

  .folder-entry.tile {
    min-height: 210px;
    display: grid;
    align-content: end;
    gap: 8px;
    padding: 18px;
  }

  .folder-entry.list {
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
  }
</style>
