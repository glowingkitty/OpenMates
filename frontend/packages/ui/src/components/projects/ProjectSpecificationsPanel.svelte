<!--
  Project Overview panel for Specifications: loads the list through the client core,
  opens the fullscreen reader, switches revisions read-only and approves the exact
  shown revision. Failures are shown, never swallowed.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../../i18n/translations';
  import type { ProjectViewModel } from '../../services/projectService';
  import {
    approveProjectSpecification, listProjectSpecifications, openProjectSpecification, type OpenedSpecification,
  } from '../../services/projectSpecificationService';
  import ProjectSpecificationsSection from './ProjectSpecificationsSection.svelte';
  import SpecificationEmbedFullscreen from '../embeds/specifications/SpecificationEmbedFullscreen.svelte';
  import type { SpecificationListItem } from '../embeds/specifications/SpecificationRevision';

  let { project }: { project: ProjectViewModel } = $props();
  let items = $state<SpecificationListItem[]>([]);
  let opened = $state<OpenedSpecification | null>(null);
  let loadFailed = $state(false);
  let actionFailed = $state(false);
  let generation = 0;

  async function load(): Promise<void> {
    const mine = ++generation;
    loadFailed = false;
    try {
      const loaded = await listProjectSpecifications(project);
      if (mine === generation) items = loaded;
    } catch (error) {
      console.error('[ProjectSpecificationsPanel] list failed:', error);
      if (mine === generation) loadFailed = true;
    }
  }
  async function open(id: string, revisionId?: string): Promise<void> {
    actionFailed = false;
    try { opened = await openProjectSpecification(project, id, revisionId); }
    catch (error) { console.error('[ProjectSpecificationsPanel] open failed:', error); actionFailed = true; }
  }
  async function approve(revisionId: string, contentHash: string): Promise<void> {
    if (!opened) return;
    actionFailed = false;
    const id = opened.id;
    try {
      await approveProjectSpecification(project, id, revisionId, contentHash);
      await open(id, revisionId);
      await load();
    } catch (error) { console.error('[ProjectSpecificationsPanel] approve failed:', error); actionFailed = true; }
  }
  onMount(() => { void load(); });
</script>

{#if loadFailed}
  <div class="spec-error" role="alert" data-testid="project-specifications-error">
    <p>{$text('specifications.project.load_error')}</p>
    <button type="button" onclick={() => void load()}>{$text('specifications.project.retry')}</button>
  </div>
{:else}
  <ProjectSpecificationsSection {items} onOpen={(id) => void open(id)} />
{/if}
{#if actionFailed}
  <p class="spec-error" role="alert" data-testid="project-specifications-action-error">{$text('specifications.project.action_error')}</p>
{/if}
{#if opened}
  <SpecificationEmbedFullscreen
    document={opened.document}
    revisions={opened.revisions}
    currentRevisionId={opened.currentRevisionId}
    viewedRevisionId={opened.viewedRevisionId}
    approval={opened.approval}
    onApprove={(revisionId, contentHash) => void approve(revisionId, contentHash)}
    onSelectRevision={(revisionId) => { if (opened) void open(opened.id, revisionId); }}
    onClose={() => { opened = null; actionFailed = false; }}
  />
{/if}

<style>
  .spec-error { color: var(--color-error, #c0392b); margin-top: var(--spacing-8); }
</style>
