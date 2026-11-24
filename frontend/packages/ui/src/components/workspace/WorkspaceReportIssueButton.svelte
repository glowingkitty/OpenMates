<!--
  WorkspaceReportIssueButton.svelte
  Reuses the canonical Settings report-issue flow from workspace surfaces.
  It passes no private title or description context and never duplicates the
  reporting form or submission behavior.
-->

<script lang="ts">
  import { tooltip } from '../../actions/tooltip';
  import { text } from '@repo/ui';
  import { panelState } from '../../stores/panelStateStore';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { reportIssueStore } from '../../stores/reportIssueStore';

  let {
    showLabel = false,
    testId = 'report-issue-button',
    onOpen = openReportIssue,
  }: { showLabel?: boolean; testId?: string; onOpen?: () => void } = $props();

  function openReportIssue(): void {
    reportIssueStore.set({
      title: '',
      issueType: 'bug_report',
      shareChat: false,
      url: typeof window === 'undefined' ? undefined : window.location.pathname,
    });
    settingsDeepLink.set('report_issue');
    panelState.openSettings();
  }
</script>

<div class="new-chat-button-wrapper report-issue-button-shell" class:with-label={showLabel} data-testid="report-issue-button-shell" data-workspace-control="report-issue">
  <button
    class="header-action report-issue-button"
    type="button"
    data-testid={testId}
    aria-label={$text('header.report_issue')}
    onclick={onOpen}
    use:tooltip
  >
    <span class="clickable-icon icon_bug top-button" aria-hidden="true"></span>
    <span class="action-label" data-testid="report-issue-label">{$text('header.report_issue')}</span>
  </button>
</div>

<style>
  .report-issue-button-shell {
    position: relative;
    z-index: var(--z-index-raised-2);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--spacing-4);
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
    box-shadow: var(--shadow-md);
    box-sizing: border-box;
    pointer-events: auto;
    transition: transform var(--duration-normal), box-shadow var(--duration-normal);
  }

  .report-issue-button-shell:hover {
    transform: scale(1.08);
    box-shadow: var(--shadow-lg);
  }

  .report-issue-button-shell:active {
    transform: scale(0.95);
    box-shadow: var(--shadow-xs);
  }

  .report-issue-button {
    all: unset;
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-4);
    box-sizing: border-box;
    min-width: 25px;
    min-height: 25px;
    cursor: pointer;
    color: var(--color-font-primary);
    font-weight: 600;
  }

  .report-issue-button:focus-visible {
    outline: 2px solid var(--color-grey-70);
    outline-offset: 3px;
    border-radius: var(--radius-3);
  }

  .top-button {
    flex: none;
    width: 25px;
    height: 25px;
  }

  .action-label {
    display: none;
    padding-inline-end: var(--spacing-4);
    white-space: nowrap;
  }

  .with-label .action-label {
    display: block;
  }
</style>
