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

  let projects = $state<ProjectViewModel[]>([]);
  let selectedProject = $state<ProjectViewModel | null>(null);
  let folders = $state<ProjectFolderViewModel[]>([]);
  let items = $state<ProjectItemViewModel[]>([]);
  let isLoading = $state(true);
  let isSaving = $state(false);
  let newProjectName = $state('');
  let newFolderName = $state('');
  let uploadInput = $state<HTMLInputElement>();

  async function refreshProjects(): Promise<void> {
    isLoading = true;
    try {
      projects = await listProjects();
      if (!selectedProject && projects.length > 0) {
        selectedProject = projects[0];
        await refreshSelectedProject();
      }
    } catch (error) {
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
    refreshSelectedProject().catch((error) => {
      console.error('[ProjectsPage] Failed to refresh selected project:', error);
      notificationStore.error('Failed to open project');
    });
  }

  onMount(() => {
    void refreshProjects();
  });
</script>

<section class="projects-page" data-testid="projects-page">
  <aside class="projects-sidebar" aria-label="Projects">
    <div class="sidebar-header">
      <h1>Projects</h1>
      <p>Organize chats, embeds, uploads, and saved AI outputs.</p>
    </div>

    <form class="create-row" onsubmit={(event) => { event.preventDefault(); void handleCreateProject(); }}>
      <input
        data-testid="project-name-input"
        bind:value={newProjectName}
        placeholder="New project name"
        aria-label="New project name"
      />
      <button data-testid="project-create-button" type="submit" disabled={isSaving || !newProjectName.trim()}>
        Create
      </button>
    </form>

    {#if isLoading}
      <p class="muted">Loading projects...</p>
    {:else if projects.length === 0}
      <p class="muted">No projects yet. Create one to start organizing saved work.</p>
    {:else}
      <div class="project-list" data-testid="project-list">
        {#each projects as project (project.project_id)}
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
  </aside>

  <main class="project-main">
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
  </main>
</section>

<style>
  .projects-page {
    display: grid;
    grid-template-columns: minmax(260px, 325px) 1fr;
    min-height: calc(100vh - 80px);
    background: var(--grey-0, #fff);
    color: var(--font-primary, #1f2937);
  }

  .projects-sidebar {
    border-right: 1px solid var(--grey-20, #e5e7eb);
    padding: 24px;
    background: var(--grey-5, #f8fafc);
  }

  .sidebar-header h1,
  .project-header h2,
  .project-section h3 {
    margin: 0;
  }

  .sidebar-header p,
  .project-header p,
  .muted {
    color: var(--font-secondary, #64748b);
  }

  .create-row {
    display: flex;
    gap: 8px;
    margin: 20px 0;
  }

  .create-row.compact {
    margin: 0;
  }

  input {
    flex: 1;
    min-width: 0;
    border: 1px solid var(--grey-30, #cbd5e1);
    border-radius: 14px;
    padding: 10px 12px;
    font: inherit;
  }

  button {
    border: 0;
    border-radius: 14px;
    padding: 10px 14px;
    background: var(--button-primary, #3b82f6);
    color: var(--font-button, #fff);
    font: inherit;
    cursor: pointer;
  }

  button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .project-list {
    display: grid;
    gap: 10px;
  }

  .project-card {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
    background: var(--grey-0, #fff);
    color: inherit;
    border: 1px solid var(--grey-20, #e5e7eb);
    text-align: left;
  }

  .project-card.active {
    border-color: var(--button-primary, #3b82f6);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--button-primary, #3b82f6) 18%, transparent);
  }

  .project-main {
    padding: 32px;
    overflow: auto;
  }

  .project-header,
  .section-title {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    margin-bottom: 24px;
  }

  .header-actions {
    display: flex;
    gap: 8px;
  }

  .eyebrow,
  .tile-icon {
    margin: 0 0 6px;
    color: var(--font-secondary, #64748b);
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
    border: 1px solid var(--grey-20, #e5e7eb);
    border-radius: 22px;
    background: var(--grey-0, #fff);
    padding: 18px;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
  }

  .tile {
    display: grid;
    gap: 8px;
    min-height: 110px;
  }

  .folder {
    background: linear-gradient(135deg, var(--grey-0, #fff), var(--grey-10, #f1f5f9));
  }

  .empty-state.large {
    max-width: 520px;
    margin: 12vh auto;
    text-align: center;
  }

  @media (max-width: 800px) {
    .projects-page {
      grid-template-columns: 1fr;
    }

    .projects-sidebar {
      border-right: 0;
      border-bottom: 1px solid var(--grey-20, #e5e7eb);
    }

    .project-header,
    .section-title {
      flex-direction: column;
    }
  }
</style>
