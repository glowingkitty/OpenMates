<!--
  ProjectsPage.svelte
  Projects V1 workspace UI for manually organizing chats, embeds, and uploads.
  Files uploaded here are converted into embeds first and then linked through
  project_items, so project storage follows the same encryption/rendering model
  as the rest of OpenMates.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { notificationStore } from '../../stores/notificationStore';
  import { panelState } from '../../stores/panelStateStore';
  import {
    createFolder,
    createProject,
    deleteProject,
    getProjectContents,
    listProjects,
    uploadFileToProject,
    type ProjectFolderViewModel,
    type ProjectItemViewModel,
    type ProjectViewModel,
  } from '../../services/projectService';

  let { variant = 'main' }: { variant?: 'main' | 'sidebar' } = $props();

  let projects = $state<ProjectViewModel[]>([]);
  let selectedProject = $state<ProjectViewModel | null>(null);
  let folders = $state<ProjectFolderViewModel[]>([]);
  let items = $state<ProjectItemViewModel[]>([]);
  let isLoading = $state(true);
  let isSaving = $state(false);
  let newProjectName = $state('');
  let newFolderName = $state('');
  let uploadInput = $state<HTMLInputElement>();
  let hasLoadError = $state(false);

  let sortedProjects = $derived([...projects].sort((a, b) => (b.encrypted.created_at || 0) - (a.encrypted.created_at || 0)));
  let recentProjects = $derived(sortedProjects.slice(0, 3));

  const PROJECT_SELECTED_EVENT = 'openmates-project-selected';
  const PROJECTS_CHANGED_EVENT = 'openmates-projects-changed';

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
      if (!selectedProject && projects.length > 0) {
        selectedProject = sortedProjects[0] ?? projects[0];
        await refreshSelectedProject();
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
      return;
    }
    const contents = await getProjectContents(selectedProject);
    folders = contents.folders;
    items = contents.items;
  }

  async function handleCreateProject(): Promise<void> {
    const name = newProjectName.trim();
    if (!name || isSaving) return;
    isSaving = true;
    try {
      const project = await createProject(name);
      projects = [project, ...projects];
      selectedProject = project;
      folders = [];
      items = [];
      newProjectName = '';
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
        selectedProject = projects[0] ?? null;
        await refreshSelectedProject();
      }
      broadcastProjectsChanged();
      notificationStore.success('Project deleted');
    } catch (error) {
      console.error('[ProjectsPage] Failed to delete project:', error);
      notificationStore.error('Failed to delete project');
    }
  }

  async function handleCreateFolder(): Promise<void> {
    if (!selectedProject) return;
    const name = newFolderName.trim();
    if (!name || isSaving) return;
    isSaving = true;
    try {
      await createFolder(selectedProject, name);
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

  function selectProject(project: ProjectViewModel): void {
    selectedProject = project;
    broadcastProjectSelected(project);
    if (variant === 'sidebar') {
      panelState.closeChats();
    }
    refreshSelectedProject().catch((error) => {
      console.error('[ProjectsPage] Failed to refresh selected project:', error);
      notificationStore.error('Failed to open project');
    });
  }

  onMount(() => {
    void refreshProjects();
    const handleProjectSelected = (event: Event) => {
      const project = (event as CustomEvent<ProjectViewModel>).detail;
      if (!project || selectedProject?.project_id === project.project_id) return;
      selectedProject = project;
      void refreshSelectedProject();
    };
    const handleProjectsChanged = () => {
      void refreshProjects();
    };
    window.addEventListener(PROJECT_SELECTED_EVENT, handleProjectSelected);
    window.addEventListener(PROJECTS_CHANGED_EVENT, handleProjectsChanged);
    return () => {
      window.removeEventListener(PROJECT_SELECTED_EVENT, handleProjectSelected);
      window.removeEventListener(PROJECTS_CHANGED_EVENT, handleProjectsChanged);
    };
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
        <button
          class:active={selectedProject?.project_id === project.project_id}
          class="project-card"
          data-testid="project-card"
          onclick={() => selectProject(project)}
          type="button"
        >
          <span>{project.name || 'Untitled project'}</span>
          <small>{project.encrypted.item_count ?? 0} items</small>
        </button>
      {/each}
    </div>
  {/if}
{/snippet}

{#snippet selectedProjectDetails()}
  {#if selectedProject}
      <header class="project-header">
        <div>
          <p class="eyebrow">Project</p>
          <h2>{selectedProject.name || 'Untitled project'}</h2>
          <p>{selectedProject.description || 'Add chats, embeds, PDFs, sheets, images, audio, video, code, mail, and files.'}</p>
        </div>
        <div class="header-actions">
          <button type="button" onclick={() => uploadInput?.click()} disabled={isSaving} data-testid="project-upload-button">
            Upload file
          </button>
          <button type="button" onclick={() => void handleDeleteProject(selectedProject as ProjectViewModel)} data-testid="project-delete-button">
            Delete
          </button>
          <input bind:this={uploadInput} type="file" onchange={handleUploadSelected} hidden />
        </div>
      </header>

      <section class="project-section">
        <div class="section-title">
          <h3>Folders</h3>
          <form class="create-row compact" onsubmit={(event) => { event.preventDefault(); void handleCreateFolder(); }}>
            <input bind:value={newFolderName} placeholder="New folder" aria-label="New folder" data-testid="project-folder-name-input" />
            <button type="submit" disabled={isSaving || !newFolderName.trim()} data-testid="project-folder-create-button">Add folder</button>
          </form>
        </div>
        {#if folders.length === 0}
          <p class="muted">No folders yet.</p>
        {:else}
          <div class="grid" data-testid="project-folder-list">
            {#each folders as folder (folder.folder_id)}
              <article class="tile folder" data-testid="project-folder-card">
                <span class="tile-icon">Folder</span>
                <strong>{folder.name || 'Untitled folder'}</strong>
              </article>
            {/each}
          </div>
        {/if}
      </section>

      <section class="project-section">
        <div class="section-title">
          <h3>Items</h3>
          <span class="muted">{items.length} saved</span>
        </div>
        {#if items.length === 0}
          <div class="empty-state" data-testid="project-empty-items">
            <h3>No project items yet</h3>
            <p>Upload a file or use “Add to project” from chats and embed fullscreen views.</p>
          </div>
        {:else}
          <div class="grid" data-testid="project-item-list">
            {#each items as item (item.project_item_id)}
              <article class="tile" data-testid="project-item-card" data-item-type={item.item_type}>
                <span class="tile-icon">{item.metadata.embed_type?.toString() || item.item_type}</span>
                <strong>{item.displayName || item.target_id}</strong>
                <small>{item.item_type}</small>
              </article>
            {/each}
          </div>
        {/if}
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
    <main class="project-main">
      <section class="projects-hero">
        <div>
          <p class="eyebrow">Projects</p>
          <h1>Continue where you left off</h1>
          <p>Pick up recent project work or create a new workspace for chats, embeds, uploads, and saved AI outputs.</p>
        </div>
        <button class="hero-create-button" data-testid="project-create-main-button" type="button" onclick={() => panelState.openChats()}>
          Create project
        </button>
      </section>

      {#if recentProjects.length > 0}
        <section class="project-section" data-testid="recent-projects-section">
          <div class="section-title">
            <h2>Continue where you left off</h2>
          </div>
          <div class="grid">
            {#each recentProjects as project (project.project_id)}
              <button class="tile project-tile" data-testid="recent-project-card" type="button" onclick={() => selectProject(project)}>
                <span class="tile-icon">Project</span>
                <strong>{project.name || 'Untitled project'}</strong>
                <small>{project.encrypted.item_count ?? 0} items</small>
              </button>
            {/each}
          </div>
        </section>
      {/if}

      <section class="project-section" data-testid="all-projects-section">
        <div class="section-title">
          <h2>All projects</h2>
          <span class="muted">{sortedProjects.length} total</span>
        </div>
        {@render projectList(false)}
      </section>

      <section class="project-section">
        {@render selectedProjectDetails()}
      </section>
    </main>
  </section>
{/if}

<style>
  .projects-page {
    min-height: calc(100vh - 80px);
    background: var(--color-grey-0);
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

  .projects-hero {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--spacing-10);
    border-radius: var(--radius-6);
    background: linear-gradient(135deg, var(--color-grey-0), var(--color-grey-10));
    padding: clamp(24px, 5vw, 56px);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.06);
  }

  .projects-hero h1,
  .project-header h2,
  .project-section h2,
  .project-section h3 {
    margin: 0;
  }

  .projects-hero p,
  .project-header p,
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
    padding: 12px 15px;
  }

  .project-card.active {
    background: color-mix(in srgb, var(--color-grey-60) 30%, transparent);
  }

  .project-main {
    padding: clamp(20px, 4vw, 48px);
    overflow: auto;
    max-width: 1200px;
    margin: 0 auto;
  }

  .project-header,
  .section-title {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--spacing-8);
    margin-bottom: 24px;
  }

  .header-actions {
    display: flex;
    gap: 8px;
  }

  .eyebrow,
  .tile-icon {
    margin: 0 0 6px;
    color: var(--color-font-secondary);
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .project-section {
    margin-top: 32px;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 14px;
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

  .load-error {
    margin: 0 15px;
    color: var(--color-font-secondary);
  }

  @media (max-width: 800px) {
    .projects-hero,
    .project-header,
    .section-title {
      flex-direction: column;
    }
  }
</style>
