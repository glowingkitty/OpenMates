<!--
    SettingsReportIssueConfirmation Component

    Shown as a sub-page of "Report Issue" immediately after a successful submission.
    Displays a clear success message and the copyable issue ID so the user can
    reference it when following up.

    The issue ID is read once from submittedIssueIdStore (via get()) at mount time.
    Written by SettingsReportIssue on success; overwritten on the next submission.

    Navigation:
    - "Submit another report" button dispatches 'navigateBack' to go back to the form.
-->
<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { get } from 'svelte/store';
    import { text } from '@repo/ui';
    import { submittedIssueIdStore } from '../../stores/reportIssueStore';
    import { copyToClipboard } from '../../utils/clipboardUtils';

    const dispatch = createEventDispatcher();

    /**
     * The issue ID received from the submission — read once from the shared store.
     *
     * We use get() instead of subscribe() because Settings.svelte's settingsViews
     * is a $derived object that can re-evaluate when reactive dependencies change
     * (auth state, user profile). This causes the {#each} block in
     * CurrentSettingsPage to re-render, which destroys and recreates this component.
     * A subscribe + onDestroy(clear) pattern would lose the ID on re-mount.
     *
     * get() captures the value once at creation time — immune to re-mounts.
     */
    const issueId = get(submittedIssueIdStore);

    /** True for 2 seconds after the user copies the issue ID. */
    let issueIdCopied = $state(false);

    /** Copy the issue ID to the clipboard and show a brief confirmation. */
    async function handleCopyIssueId() {
        if (!issueId) return;
        try {
            const result = await copyToClipboard(issueId);
            if (result.success) {
                issueIdCopied = true;
                setTimeout(() => { issueIdCopied = false; }, 2000);
            }
        } catch {
            // Clipboard API unavailable — silently ignore.
        }
    }

    /** Navigate back to the report issue form so the user can submit again. */
    function handleSubmitAnother() {
        dispatch('navigateBack');
    }
</script>

<div class="confirmation-wrapper" data-testid="report-issue-confirmation">
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
                    class:copied={issueIdCopied}
                    onclick={handleCopyIssueId}
                    aria-label={$text('common.copy')}
                >
                    {issueIdCopied
                        ? $text('common.not_found.url_copied')
                        : $text('common.copy')}
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
        gap: var(--spacing-8);
        padding: var(--spacing-16) var(--spacing-12) var(--spacing-12);
        text-align: center;
    }

    .confirmation-icon {
        width: 56px;
        height: 56px;
        border-radius: 50%;
        background: var(--color-success, #4caf50);
        color: var(--color-grey-0);
        font-size: 28px;
        line-height: 56px;
        flex-shrink: 0;
    }

    .confirmation-heading {
        font-size: var(--font-size-h3-mobile);
        font-weight: 600;
        color: var(--color-font-primary);
        margin: 0;
    }

    .confirmation-body {
        font-size: var(--font-size-small);
        color: var(--color-font-secondary);
        margin: 0;
        max-width: 320px;
    }

    /* Issue ID block */
    .issue-id-block {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--spacing-4);
        width: 100%;
        max-width: 360px;
        border-radius: var(--border-radius-md, 6px);
        padding: var(--spacing-6) var(--spacing-8);
        background: var(--color-grey-10);
    }

    .issue-id-label {
        font-size: var(--font-size-xxs);
        font-weight: 500;
        color: var(--color-grey-100);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .issue-id-row {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
        flex-wrap: wrap;
        justify-content: center;
    }

    .issue-id-value {
        font-family: monospace;
        font-size: var(--font-size-xs);
        color: var(--color-grey-100);
        word-break: break-all;
    }

    /* Submit another button */
    .another-btn {
        margin-top: var(--spacing-4);
        padding: var(--spacing-5) var(--spacing-10);
        border: 1px solid var(--color-border, #ccc);
        border-radius: var(--border-radius-md, 6px);
        background: transparent;
        color: var(--color-font-primary);
        font-size: var(--font-size-small);
        cursor: pointer;
        transition: background var(--duration-fast);
    }

    .another-btn:hover {
        background: var(--color-surface-2, #f5f5f5);
    }
</style>
