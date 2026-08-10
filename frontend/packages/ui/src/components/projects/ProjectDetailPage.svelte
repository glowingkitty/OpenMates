<!--
  ProjectDetailPage.svelte
  Canonical encrypted Project detail surface for stable nested routes.
  Metadata mutations delegate to projectService through the domain adapter so
  plaintext never reaches the Projects API.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import WorkspaceDetailHeader from '../workspace/WorkspaceDetailHeader.svelte';
  import WorkspaceReportIssueButton from '../workspace/WorkspaceReportIssueButton.svelte';
  import { projectDetailAdapter } from '../workspace/detailMetadataAdapters';
  import type { ProjectViewModel } from '../../services/projectService';
  import { text } from '@repo/ui';

  let { projectId }: { projectId: string } = $props();
  let project = $state<ProjectViewModel | null>(null);
  let hasError = $state(false);
  let domainLabel = $derived($text('navigation.projects'));

  onMount(() => { void load(); });
  async function load(): Promise<void> {
    hasError = false;
    try { project = await projectDetailAdapter.load(projectId); }
    catch (loadError) { hasError = true; console.error('[ProjectDetailPage] Failed to load project:', loadError); }
  }
  async function saveTitle(title: string): Promise<void> { if (project) project = await projectDetailAdapter.saveTitle(project, title); }
  async function saveDescription(description: string): Promise<void> { if (project) project = await projectDetailAdapter.saveDescription(project, description); }
</script>

<section class="detail-page" data-testid="project-detail-page">
  <nav><a href="/projects">{domainLabel}</a><WorkspaceReportIssueButton /></nav>
  {#if project}
    <WorkspaceDetailHeader title={project.name || $text('common.detail_untitled', { values: { item: domainLabel } })} description={project.description || ''} category="productivity" icon="folder" writable={true} onSaveTitle={saveTitle} onSaveDescription={saveDescription} metadata={$text('common.detail_items_count', { values: { count: project.encrypted.item_count ?? 0 } })} />
  {:else if hasError}
    <div class="state" role="alert"><p>{$text('common.detail_load_error', { values: { item: domainLabel } })}</p><button type="button" onclick={() => void load()}>{$text('common.retry')}</button></div>
  {:else}<div class="state">{$text('common.detail_loading', { values: { item: domainLabel } })}</div>{/if}
</section>

<style>
  .detail-page { width: 100%; height: 100%; overflow: auto; background: var(--color-grey-0); color: var(--color-font-primary); }
  nav { display: flex; align-items: center; justify-content: space-between; padding: var(--spacing-5) var(--spacing-8); }
  nav a { color: var(--color-font-primary); }
  .state { display: grid; min-height: 240px; place-content: center; gap: var(--spacing-5); text-align: center; }
</style>
