<!--
  Project Overview panel for Checks: lists the Project's Checks as embed previews (from
  GET /v1/user-checks?project_hash=...), opens the shared Check fullscreen, starts runs
  and records Confirm/Reject for pending human sources. Failures are shown, never swallowed.
  Renders nothing while the Project has no Check. Spec: checks.gui.fullscreen.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../../i18n/translations';
  import type { ProjectViewModel } from '../../services/projectService';
  import {
    confirmProjectCheckSource, listProjectChecks, reloadProjectCheck, startProjectCheckRun,
  } from '../../services/projectCheckService';
  import CheckEmbedPreview from '../embeds/checks/CheckEmbedPreview.svelte';
  import CheckEmbedFullscreen from '../embeds/checks/CheckEmbedFullscreen.svelte';
  import type { CheckView, HumanDecision } from '../embeds/checks/checkTypes';

  let { project }: { project: ProjectViewModel } = $props();
  let items = $state<CheckView[]>([]);
  let opened = $state<CheckView | null>(null);
  let loadFailed = $state(false);
  let actionFailed = $state(false);
  let generation = 0;

  async function load(): Promise<void> {
    const mine = ++generation;
    loadFailed = false;
    try {
      const loaded = await listProjectChecks(project);
      if (mine === generation) items = loaded;
    } catch (error) {
      console.error('[ProjectChecksPanel] list failed:', error);
      if (mine === generation) loadFailed = true;
    }
  }
  async function refresh(id: string): Promise<void> {
    const fresh = await reloadProjectCheck(project, id);
    items = items.map((item) => (item.id === id ? fresh : item));
    if (opened?.id === id) opened = fresh;
  }
  async function act(task: () => Promise<void>): Promise<void> {
    actionFailed = false;
    try { await task(); }
    catch (error) { console.error('[ProjectChecksPanel] action failed:', error); actionFailed = true; }
  }
  const run = (id: string) => act(async () => { await startProjectCheckRun(project, id); await refresh(id); });
  const confirm = (bindingId: string, decision: HumanDecision) => act(async () => {
    if (!opened) return;
    await confirmProjectCheckSource(project, opened, bindingId, decision);
    await refresh(opened.id);
  });
  onMount(() => { void load(); });
</script>

{#if loadFailed}
  <div class="check-error" role="alert" data-testid="project-checks-error">
    <p>{$text('checks.project.load_error')}</p>
    <button type="button" onclick={() => void load()}>{$text('checks.project.retry')}</button>
  </div>
{:else if items.length}
  <section class="project-checks" data-testid="project-checks-section" aria-label={$text('checks.project.heading')}>
    <h2>{$text('checks.project.heading')}</h2>
    <div class="check-grid" data-embed-result-context="results">
      {#each items as check (check.id)}
        <div data-testid={`project-check-${check.id}`}>
          <CheckEmbedPreview id={`project-check-${check.id}`} {check} onFullscreen={() => { opened = check; }} />
        </div>
      {/each}
    </div>
  </section>
{/if}
{#if actionFailed}
  <p class="check-error" role="alert" data-testid="project-checks-action-error">{$text('checks.project.action_error')}</p>
{/if}
{#if opened}
  <CheckEmbedFullscreen check={opened} onClose={() => { opened = null; actionFailed = false; }}
    onRun={() => { if (opened) void run(opened.id); }} onCancel={() => {}}
    onConfirm={(bindingId, decision) => void confirm(bindingId, decision)}
    onSelectRun={() => {}} onOpenTestResult={() => {}} />
{/if}

<style>
  .project-checks { display: flex; flex-direction: column; gap: var(--spacing-8); margin-top: var(--spacing-10); min-width: 0; }
  h2 { margin: 0; font-size: var(--font-size-h3); color: var(--color-font-primary); }
  .check-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 300px)); justify-content: start; gap: var(--spacing-8); }
  .check-error { color: var(--color-error, #c0392b); margin-top: var(--spacing-8); }
</style>
