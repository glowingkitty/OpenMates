<!-- Public, deterministic composition of the actual workflow landing components.
     Keeps preview comparisons independent of account data and API mutations. -->
<script lang="ts">
  import WorkspaceHomeShell from '../workspace/WorkspaceHomeShell.svelte';
  import WorkspacePromptComposer from '../workspace/WorkspacePromptComposer.svelte';
  import { text } from '../../i18n/translations';

  let { greetingName = 'there' }: { greetingName?: string } = $props();
  let value = $state('');
  let showAllMode = $state(false);
  const recent = {
    id: 'workflow-fixture', title: 'Weekly AI events',
    summary: 'Every day, 09:00 - Keep latest 5 encrypted runs',
    badge: 'Paused', category: 'technology', icon: 'calendar-days', source: 'recent' as const
  };
  const actionItems = [recent,
    { id: 'starter-rain', title: 'Daily weather and news', summary: 'Rain timing and the latest articles in a new chat', badge: 'Starter', category: 'weather', appId: 'weather', icon: 'cloud-rain', source: 'example' as const },
    { id: 'starter-news', title: 'Weekly AI events', summary: 'Discover AI events for the upcoming week', badge: 'Starter', category: 'technology', appId: 'news', icon: 'calendar-days', source: 'example' as const },
    { id: 'starter-apartments', title: 'Find new apartments every hour', summary: 'Only previously undelivered listings', badge: 'Starter', category: 'productivity', appId: 'home', icon: 'house', source: 'example' as const }
  ];
</script>

<WorkspaceHomeShell
  surface="workflows" testId="workflows-start-screen"
  heading={`Hey ${greetingName}!`} subtitle="What do you want to automate next?"
  {actionItems} actionItemsTestId="workflow-mixed-row" itemTestId="workflow-landing-card"
  showReportIssue {showAllMode} showAllLabel="Show all" showAllTestId="workflows-show-all"
  allItems={[recent]} allItemsViewTestId="all-workflows-view" allItemsGridTestId="all-workflows-grid"
  allItemsToolbarTestId="workflows-all-toolbar" allItemTestId="workflow-landing-card"
  backTestId="workflows-back-to-recent" searchTestId="workflows-search"
  onShowAll={() => { showAllMode = true; }} onBackToRecent={() => { showAllMode = false; }}
  onSearchAll={() => {}} onActionItem={() => {}} onAllItem={() => {}}
>
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
