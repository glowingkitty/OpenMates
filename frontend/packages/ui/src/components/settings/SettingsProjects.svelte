<!--
  SettingsProjects.svelte
  Project settings hub and per-project detail view.

  Projects keep source metadata encrypted client-side. This page only displays
  decrypted project names plus bounded source status, and links future write/check
  controls to the existing Project settings route instead of duplicating controls
  inside the Projects workspace page.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import {
        SettingsButton,
        SettingsCard,
        SettingsDetailRow,
        SettingsInfoBox,
        SettingsItem,
        SettingsPageContainer,
        SettingsSectionHeading,
    } from './elements';
    import {
        listProjects,
        listProjectSources,
        type ProjectSourceViewModel,
        type ProjectViewModel,
    } from '../../services/projectService';

    let { activeSettingsView = 'projects' }: { activeSettingsView?: string } = $props();

    const dispatch = createEventDispatcher();

    let projects = $state<ProjectViewModel[]>([]);
    let sources = $state<ProjectSourceViewModel[]>([]);
    let isLoading = $state(true);
    let loadError = $state('');
    let loadedRoute = $state('');

    let selectedProjectId = $derived(activeSettingsView.match(/^projects\/([^/]+)$/)?.[1] ?? null);
    let selectedProject = $derived(projects.find((project) => project.project_id === selectedProjectId) ?? null);
    let sortedProjects = $derived([...projects].sort((a, b) => (b.encrypted.created_at || 0) - (a.encrypted.created_at || 0)));

    $effect(() => {
        if (loadedRoute === activeSettingsView) return;
        loadedRoute = activeSettingsView;
        void loadProjects();
    });

    async function loadProjects(): Promise<void> {
        isLoading = true;
        loadError = '';
        try {
            const nextProjects = await listProjects();
            projects = nextProjects;
            const project = selectedProjectId
                ? nextProjects.find((candidate) => candidate.project_id === selectedProjectId)
                : null;
            sources = project ? await listProjectSources(project) : [];
        } catch (error) {
            console.error('[SettingsProjects] Failed to load Projects settings:', error);
            loadError = $text('settings.projects.load_error');
            sources = [];
        } finally {
            isLoading = false;
        }
    }

    function openProject(project: ProjectViewModel): void {
        dispatch('openSettings', {
            settingsPath: `projects/${project.project_id}`,
            direction: 'forward',
            icon: 'project',
            title: project.name || 'Untitled project',
            cameFrom: 'projects',
        });
    }
</script>

<SettingsPageContainer maxWidth="wide">
    <div data-testid="project-settings-page">
        {#if isLoading}
            <SettingsInfoBox type="info">
                <p><strong>{$text('settings.projects.loading_title')}</strong></p>
                <p>{$text('settings.projects.loading_description')}</p>
            </SettingsInfoBox>
        {:else if loadError}
            <SettingsInfoBox type="warning">
                <p><strong>{$text('settings.projects.load_error_title')}</strong></p>
                <p>{loadError}</p>
            </SettingsInfoBox>
            <SettingsButton variant="secondary" dataTestid="project-settings-retry-button" onClick={() => void loadProjects()}>
                {$text('settings.projects.retry')}
            </SettingsButton>
        {:else if selectedProjectId && selectedProject}
            <div data-testid="project-settings-title">
                <SettingsSectionHeading title={selectedProject.name || 'Untitled project'} icon="project" />
            </div>
            <SettingsCard>
                <SettingsDetailRow label="Name" value={selectedProject.name || 'Untitled project'} highlight />
                <SettingsDetailRow label="Items" value={`${selectedProject.encrypted.item_count ?? 0}`} />
                <SettingsDetailRow label="Write policy" value="Always ask before writes" />
                <SettingsDetailRow label="Automated checks" value="Not configured" muted />
            </SettingsCard>

            <SettingsSectionHeading title="Connected sources" icon="project" />
            {#if sources.length === 0}
                <SettingsInfoBox type="info">
                    <p><strong>No remote sources connected</strong></p>
                    <p>Use the OpenMates CLI remote-access bridge to attach a folder or repository.</p>
                </SettingsInfoBox>
            {:else}
                {#each sources as source (source.source_id)}
                    <div data-testid="project-settings-source-card">
                        <SettingsCard>
                            <SettingsDetailRow label="Source" value={source.displayName || source.source_id} highlight />
                            <SettingsDetailRow label="Type" value={source.source_type.replaceAll('_', ' ')} />
                            <SettingsDetailRow label="Status" value={source.status.replaceAll('_', ' ')} />
                            <SettingsDetailRow label="Capabilities" value={source.capabilities.join(', ') || 'None'} muted />
                        </SettingsCard>
                    </div>
                {/each}
            {/if}
        {:else if selectedProjectId}
            <SettingsInfoBox type="warning">
                <p><strong>Project not found</strong></p>
                <p>This project may have been deleted or may not be available on this device.</p>
            </SettingsInfoBox>
        {:else}
            <SettingsSectionHeading title={$text('settings.projects')} icon="project" />
            {#if sortedProjects.length === 0}
                <SettingsInfoBox type="info">
                    <p><strong>No projects yet</strong></p>
                    <p>Create a project first, then return here to manage project-specific source permissions.</p>
                </SettingsInfoBox>
            {:else}
                {#each sortedProjects as project (project.project_id)}
                    <SettingsItem
                        type="subsubmenu"
                        icon="project"
                        title={project.name || 'Untitled project'}
                        subtitleTop={`${project.encrypted.item_count ?? 0} items`}
                        data-testid="project-settings-project-row"
                        onClick={() => openProject(project)}
                    />
                {/each}
            {/if}
        {/if}
    </div>
</SettingsPageContainer>
