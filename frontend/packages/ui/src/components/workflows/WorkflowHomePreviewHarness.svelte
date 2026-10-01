<!-- Public, deterministic composition of the actual workflow landing components.
     Keeps preview comparisons independent of account data and API mutations. -->
<script lang="ts">
  import WorkspaceHomeShell from '../workspace/WorkspaceHomeShell.svelte';
  import WorkspacePromptComposer from '../workspace/WorkspacePromptComposer.svelte';
  import { sortAllWorkflows, sortWorkflowContinue } from './workflowHomeSorting';
  import { text } from '../../i18n/translations';

  let { greetingName = 'there', empty = false }: { greetingName?: string; empty?: boolean } = $props();
  let value = $state('');
  let browseMode = $state<'home' | 'workflows' | 'templates'>('home');
  let sortMode = $state<'recent' | 'running-next'>('recent');
  const now = Math.floor(Date.now() / 1000);
  const actionItems = [
    { id: 'workflow-fixture', title: 'Weekly AI events', summary: 'Every day, 09:00 - Keep latest 5 encrypted runs', badge: 'Paused', category: 'technology', icon: 'calendar-days', source: 'recent' as const, created_at: now - 60, updated_at: now - 60, next_run_at: null, enabled: false },
    { id: 'workflow-rain', title: 'Daily weather and news', summary: 'Rain timing and the latest articles in a new chat', badge: 'Enabled', category: 'weather', icon: 'cloud-rain', source: 'recent' as const, created_at: now - 3600, updated_at: now - 3600, next_run_at: now + 300, enabled: true },
    { id: 'workflow-news', title: 'Weekly AI events digest', summary: 'Discover AI events for the upcoming week', badge: 'Enabled', category: 'technology', icon: 'calendar-days', source: 'recent' as const, created_at: now - 7200, updated_at: now - 7200, next_run_at: now + 7200, enabled: true },
    { id: 'workflow-apartments', title: 'Find new apartments every hour', summary: 'Only previously undelivered listings', badge: 'Paused', category: 'productivity', icon: 'house', source: 'recent' as const, created_at: now - 90000, updated_at: now - 90000, next_run_at: null, enabled: false }
  ];
  const templates = [
    { id: 'daily-planning-reminder', title: 'Daily planning reminder', summary: 'A morning message to choose your priorities for the day', badge: 'Template', category: 'productivity', icon: 'sun', source: 'example' as const },
    { id: 'weekly-review-reminder', title: 'Weekly review reminder', summary: 'A Friday prompt to reflect and plan the next week', badge: 'Template', category: 'productivity', icon: 'calendar-days', source: 'example' as const },
  ];
</script>

<WorkspaceHomeShell
  surface="workflows" testId="workflows-start-screen"
  heading={`Hey ${greetingName}!`} subtitle="What do you want to automate next?"
  actionItems={empty ? [] : sortWorkflowContinue(actionItems)} actionItemsTestId="workflow-mixed-row" itemTestId="workflow-landing-card"
  showReportIssue showAllMode={browseMode !== 'home'} showAllLabel="Show my workflows" showAllTestId="workflows-show-all"
  browseLabel="Show templates" browseTestId="workflows-show-templates"
  allItemsHeading={browseMode === 'templates' ? 'Templates' : 'My workflows'}
  allItems={browseMode === 'templates' ? templates : empty ? [] : sortAllWorkflows(actionItems, sortMode)} allItemsViewTestId="all-workflows-view" allItemsGridTestId="all-workflows-grid"
  allItemsToolbarTestId="workflows-all-toolbar" allItemTestId="workflow-landing-card"
  backTestId="workflows-back-to-recent" searchTestId="workflows-search"
  onShowAll={() => { browseMode = 'workflows'; }} onBrowse={() => { browseMode = 'templates'; }} onBackToRecent={() => { browseMode = 'home'; }}
  onSearchAll={() => {}} onActionItem={() => {}} onAllItem={() => {}}
>
  <svelte:fragment slot="top-right">
    {#if browseMode === 'workflows'}
      <label>Sort <select data-testid="workflows-sort" bind:value={sortMode}><option value="recent">Last updated</option><option value="running-next">Running next first</option></select></label>
    {/if}
  </svelte:fragment>
  <svelte:fragment slot="composer">
    <WorkspacePromptComposer
      surface="workflows" bind:value placeholder={$text('workflows.builder.new_workflow_placeholder')}
      submitLabel="Create workflow" submittingLabel="Creating..." disabled={false} submitting={false}
      testId="workflow-input-composer" inputTestId="workflow-input-textarea"
      submitTestId="workflow-input-submit" micTestId="workflow-input-mic"
      onSubmit={() => {}} onMicClick={() => {}}
    />
  </svelte:fragment>
</WorkspaceHomeShell>
