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

<button
  class="clickable-icon icon_bug report-issue-button"
  type="button"
  data-testid="report-issue-button"
  aria-label={$text('header.report_issue')}
  title={$text('header.report_issue')}
  onclick={openReportIssue}
></button>

<style>
  .report-issue-button {
    position: relative;
    z-index: var(--z-index-raised-2);
    width: 44px;
    height: 44px;
    flex: 0 0 44px;
  }
</style>
