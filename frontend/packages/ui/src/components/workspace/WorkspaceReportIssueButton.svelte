<!--
  WorkspaceReportIssueButton.svelte
  Reuses the canonical Settings report-issue flow from workspace surfaces.
  It passes no private title or description context and never duplicates the
  reporting form or submission behavior.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import { panelState } from '../../stores/panelStateStore';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { reportIssueStore } from '../../stores/reportIssueStore';

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

<div class="report-issue-button-shell" data-testid="report-issue-button-shell">
  <button
    class="clickable-icon icon_bug report-issue-button"
    type="button"
    data-testid="report-issue-button"
    aria-label={$text('header.report_issue')}
    title={$text('header.report_issue')}
    onclick={openReportIssue}
  ></button>
</div>

<style>
  .report-issue-button-shell {
    position: relative;
    z-index: var(--z-index-raised-2);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--spacing-4);
    border-radius: 40px;
    background: var(--color-grey-10);
    box-shadow: var(--shadow-md);
    box-sizing: border-box;
  }

  .report-issue-button {
    flex: 0 0 auto;
  }
</style>
