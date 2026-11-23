<!--
    ReportIssueScreenshots — thumbnail row, count ("2/5") and error line for the
    screenshots attached to a Report Issue form. Attaching and removing is owned
    by SettingsReportIssue; this component only renders.

    Preview: /dev/preview/settings/ReportIssueScreenshots
    Tests: frontend/apps/web_app/tests/components/report-issue-screenshots.spec.ts
           frontend/apps/web_app/tests/report-issue-flow.spec.ts
-->
<script lang="ts">
    import { text } from '@repo/ui';

    let {
        screenshots = [],
        error = '',
        disabled = false,
        maxCount = 5,
        onRemove = () => undefined
    }: {
        screenshots?: string[];
        error?: string;
        disabled?: boolean;
        maxCount?: number;
        onRemove?: (index: number) => void;
    } = $props();
</script>

{#if screenshots.length > 0 || error}
    <div class="input-group screenshot-section" data-testid="screenshot-section">
        {#if screenshots.length > 0}
            <p class="screenshot-count" data-testid="screenshot-count">
                {screenshots.length}/{maxCount}
            </p>
            <div class="screenshot-row">
                {#each screenshots as src, index (index)}
                    <div class="screenshot-item" data-testid="screenshot-preview" data-index={index}>
                        <img
                            {src}
                            alt={$text('settings.report_issue.screenshot_preview_alt')}
                            class="screenshot-preview"
                        />
                        <button
                            type="button"
                            class="screenshot-remove-btn"
                            data-testid="screenshot-remove"
                            data-index={index}
                            onclick={() => onRemove(index)}
                            {disabled}
                            aria-label={$text('settings.report_issue.screenshot_remove')}
                            title={$text('settings.report_issue.screenshot_remove')}
                        >
                            ×
                        </button>
                    </div>
                {/each}
            </div>
        {/if}
        {#if error}
            <p class="screenshot-error" data-testid="screenshot-error">{error}</p>
        {/if}
    </div>
{/if}

<style>
    .screenshot-section {
        gap: var(--spacing-4);
    }

    .screenshot-count {
        margin: 0;
        font-size: var(--font-size-xs);
        color: var(--color-font-secondary);
    }

    .screenshot-row {
        display: flex;
        flex-wrap: wrap;
        gap: var(--spacing-6);
        /* room for the remove buttons that overhang each thumbnail's top-right corner */
        padding-top: 8px;
        padding-right: 8px;
    }

    .screenshot-item {
        position: relative;
        width: 72px;
        height: 72px;
    }

    .screenshot-preview {
        width: 100%;
        height: 100%;
        border-radius: var(--border-radius-md, 6px);
        border: 1px solid var(--color-border, #ccc);
        object-fit: cover;
    }

    .screenshot-remove-btn {
        position: absolute;
        top: -6px;
        right: -6px;
        /* override the global button sizing so the control stays a small circle */
        box-sizing: border-box;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 22px;
        min-width: 0;
        max-width: 22px;
        height: 22px;
        min-height: 0;
        margin: 0;
        padding: 0;
        box-shadow: none;
        border: 1px solid var(--color-danger, #e53935);
        border-radius: 50%;
        background: var(--color-background, #fff);
        color: var(--color-danger, #e53935);
        font-size: var(--font-size-small, 14px);
        line-height: 1;
        cursor: pointer;
    }

    .screenshot-remove-btn:hover:not(:disabled) {
        background: rgba(229, 57, 53, 0.08);
    }

    .screenshot-remove-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .screenshot-error {
        font-size: var(--font-size-xs);
        color: var(--color-danger, #e53935);
        margin: 0;
    }
</style>
