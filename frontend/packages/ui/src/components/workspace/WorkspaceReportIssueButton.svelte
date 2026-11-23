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

  /** toolbar: pill inside a HeaderActionMenu. showLabel: start screens show "Report issue" next to the icon where it fits, like Chats. */
  let { toolbar = false, showLabel = false }: { toolbar?: boolean; showLabel?: boolean } = $props();

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

{#if toolbar}
  <div class="new-chat-button-wrapper" data-testid="report-issue-button-shell">
    <button type="button" class="header-action" data-testid="report-issue-button" aria-label={$text('header.report_issue')} onclick={openReportIssue} use:tooltip><span class="clickable-icon icon_bug top-button" aria-hidden="true"></span><span class="action-label">{$text('header.report_issue')}</span></button>
  </div>
{:else}
<div class="report-issue-button-shell" class:with-label={showLabel} data-testid="report-issue-button-shell">
  <button
    class="report-issue-button"
    type="button"
    data-testid="report-issue-button"
    aria-label={$text('header.report_issue')}
    title={showLabel ? undefined : $text('header.report_issue')}
    onclick={openReportIssue}
  ><span class="clickable-icon icon_bug" aria-hidden="true"></span>{#if showLabel}<span class="report-issue-label" data-testid="report-issue-label">{$text('header.report_issue')}</span>{/if}</button>
</div>

{/if}

<style>
  .new-chat-button-wrapper { background-color:var(--color-grey-10); border-radius:40px; padding:var(--spacing-4); box-shadow:var(--shadow-md); display:flex; align-items:center; justify-content:center; pointer-events:auto; }

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

  /* Same text treatment as the Chats header pill (HeaderActionMenu .action-label). */
  .report-issue-label {
    padding-inline-end: var(--spacing-4);
    white-space: nowrap;
  }
</style>
