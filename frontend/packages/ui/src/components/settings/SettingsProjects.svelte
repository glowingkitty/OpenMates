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
        SettingsButtonGroup,
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
        getProjectSettings,
        updateProjectSettings,
        type ProjectSourceViewModel,
        type ProjectViewModel,
    } from '../../services/projectService';
    import type { ProjectWriteMode } from '../../services/projectRemoteSources';

    let { activeSettingsView = 'projects' }: { activeSettingsView?: string } = $props();

    const dispatch = createEventDispatcher();

    let projects = $state<ProjectViewModel[]>([]);
    let sources = $state<ProjectSourceViewModel[]>([]);
    let writeMode = $state<ProjectWriteMode>('always_ask');
    let isLoading = $state(true);
    let isSavingSettings = $state(false);
    let loadError = $state('');
    let saveError = $state('');
    let saveMessage = $state('');
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
            if (project) {
                const [projectSources, projectSettings] = await Promise.all([
                    listProjectSources(project),
                    getProjectSettings(project),
                ]);
                sources = projectSources;
                writeMode = projectSettings.writeMode;
            } else {
                sources = [];
                writeMode = 'always_ask';
            }
        } catch (error) {
            console.error('[SettingsProjects] Failed to load Projects settings:', error);
            loadError = $text('settings.projects.load_error');
            sources = [];
            writeMode = 'always_ask';
        } finally {
            isLoading = false;
        }
    }

    async function saveWriteMode(nextWriteMode: ProjectWriteMode): Promise<void> {
        if (!selectedProject || isSavingSettings) return;
        isSavingSettings = true;
        saveError = '';
        saveMessage = '';
        try {
            const updated = await updateProjectSettings(selectedProject, nextWriteMode, {
                protected_path_patterns: [],
                automated_checks: 'not_configured',
            });
            writeMode = updated.writeMode;
            saveMessage = 'Project write policy saved.';
        } catch (error) {
            console.error('[SettingsProjects] Failed to save Project write mode:', error);
            saveError = 'Could not save Project write policy. Please try again.';
        } finally {
            isSavingSettings = false;
        }
    }

    function writeModeLabel(mode: ProjectWriteMode): string {
        return mode === 'auto_approve_safe_writes'
            ? 'Auto approve safe writes'
            : 'Always ask before writes';
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
                <SettingsDetailRow label="Write policy" value={writeModeLabel(writeMode)} />
                <SettingsDetailRow label="Automated checks" value="Not configured" muted />
            </SettingsCard>
            <SettingsButtonGroup align="left">
                <SettingsButton
                    variant={writeMode === 'always_ask' ? 'primary' : 'secondary'}
                    disabled={isSavingSettings || writeMode === 'always_ask'}
                    loading={isSavingSettings && writeMode !== 'always_ask'}
                    dataTestid="project-settings-write-mode-always-ask"
                    onClick={() => void saveWriteMode('always_ask')}
                >
                    Always ask
                </SettingsButton>
                <SettingsButton
                    variant={writeMode === 'auto_approve_safe_writes' ? 'primary' : 'secondary'}
                    disabled={isSavingSettings || writeMode === 'auto_approve_safe_writes'}
                    loading={isSavingSettings && writeMode !== 'auto_approve_safe_writes'}
                    dataTestid="project-settings-write-mode-safe-writes"
                    onClick={() => void saveWriteMode('auto_approve_safe_writes')}
                >
                    Auto approve safe writes
                </SettingsButton>
            </SettingsButtonGroup>
            {#if saveMessage}
                <SettingsInfoBox type="success">
                    <p>{saveMessage}</p>
                </SettingsInfoBox>
            {/if}
            {#if saveError}
                <SettingsInfoBox type="warning">
                    <p>{saveError}</p>
                </SettingsInfoBox>
            {/if}

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
