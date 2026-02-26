<!--
    SettingsReportIssueConfirmation Component

    Shown as a sub-page of "Report Issue" immediately after a successful submission.
    Displays a clear success message and the copyable issue ID so the user can
    reference it when following up.

    The issue ID is read from submittedIssueIdStore, written by SettingsReportIssue
    on success. The store is cleared when this component is destroyed.

    Navigation:
    - "Submit another report" button dispatches 'navigateBack' to go back to the form.
-->
<script lang="ts">
    import { onDestroy, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { submittedIssueIdStore } from '../../stores/reportIssueStore';

    const dispatch = createEventDispatcher();

    /** The issue ID received from the submission — read from the shared store. */
    let issueId = $state('');
    /** True for 2 seconds after the user copies the issue ID. */
    let issueIdCopied = $state(false);

    // Subscribe to the store and keep local state in sync.
    const unsubscribe = submittedIssueIdStore.subscribe((id) => {
        issueId = id;
    });

    // Clear the store when this page is destroyed so stale IDs don't persist.
    onDestroy(() => {
        unsubscribe();
        submittedIssueIdStore.set('');
    });

    /** Copy the issue ID to the clipboard and show a brief confirmation. */
    async function handleCopyIssueId() {
        if (!issueId) return;
        try {
            await navigator.clipboard.writeText(issueId);
            issueIdCopied = true;
            setTimeout(() => { issueIdCopied = false; }, 2000);
        } catch {
            // Clipboard API unavailable — silently ignore.
        }
    }

    /** Navigate back to the report issue form so the user can submit again. */
    function handleSubmitAnother() {
        dispatch('navigateBack');
    }
</script>

<div class="confirmation-wrapper">
    <!-- Checkmark icon -->
    <div class="confirmation-icon" aria-hidden="true">✓</div>

    <!-- Heading -->
    <h2 class="confirmation-heading">
        {$text('settings.report_issue.confirmation_heading')}
    </h2>

    <!-- Body text -->
    <p class="confirmation-body">
        {$text('settings.report_issue.confirmation_body')}
    </p>

    <!-- Issue ID block -->
    {#if issueId}
        <div class="issue-id-block">
            <span class="issue-id-label">
                {$text('settings.report_issue.issue_id_label')}
            </span>
            <div class="issue-id-row">
                <code class="issue-id-value">{issueId}</code>
                <button
                    type="button"
                    class="copy-btn"
                    class:copied={issueIdCopied}
                    onclick={handleCopyIssueId}
                    aria-label={$text('settings.report_issue.copy_issue_id')}
                >
                    {issueIdCopied
                        ? $text('settings.report_issue.issue_id_copied')
                        : $text('settings.report_issue.copy_issue_id')}
                </button>
            </div>
        </div>
    {/if}

    <!-- Submit another report -->
    <button
        type="button"
        class="another-btn"
        onclick={handleSubmitAnother}
    >
        {$text('settings.report_issue.confirmation_submit_another')}
    </button>
</div>

<style>
    .confirmation-wrapper {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        padding: 32px 24px 24px;
        text-align: center;
    }

    .confirmation-icon {
        width: 56px;
        height: 56px;
        border-radius: 50%;
        background: var(--color-success, #4caf50);
        color: #fff;
        font-size: 28px;
        line-height: 56px;
        flex-shrink: 0;
    }

    .confirmation-heading {
        font-size: 18px;
        font-weight: 600;
        color: var(--color-font-primary);
        margin: 0;
    }

    .confirmation-body {
        font-size: 14px;
        color: var(--color-font-secondary);
        margin: 0;
        max-width: 320px;
    }

    /* Issue ID block */
    .issue-id-block {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        width: 100%;
        max-width: 360px;
        background: var(--color-surface-2, #f5f5f5);
        border-radius: var(--border-radius-md, 6px);
        padding: 12px 16px;
    }

    .issue-id-label {
        font-size: 12px;
        font-weight: 500;
        color: var(--color-font-secondary);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .issue-id-row {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        justify-content: center;
    }

    .issue-id-value {
        font-family: monospace;
        font-size: 13px;
        color: var(--color-font-primary);
        word-break: break-all;
    }

    .copy-btn {
        padding: 4px 10px;
        border: 1px solid var(--color-border, #ccc);
        border-radius: var(--border-radius-sm, 4px);
        background: var(--color-surface-1, #fff);
        color: var(--color-font-primary);
        font-size: 12px;
        cursor: pointer;
        white-space: nowrap;
        transition: background 0.15s;
        flex-shrink: 0;
    }

    .copy-btn:hover {
        background: var(--color-surface-3, #e8e8e8);
    }

    .copy-btn.copied {
        border-color: var(--color-success, #4caf50);
        color: var(--color-success, #4caf50);
    }

    /* Submit another button */
    .another-btn {
        margin-top: 8px;
        padding: 10px 20px;
        border: 1px solid var(--color-border, #ccc);
        border-radius: var(--border-radius-md, 6px);
        background: transparent;
        color: var(--color-font-primary);
        font-size: 14px;
        cursor: pointer;
        transition: background 0.15s;
    }

    .another-btn:hover {
        background: var(--color-surface-2, #f5f5f5);
    }
</style>
