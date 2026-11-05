<!-- frontend/packages/ui/src/components/enter_message/PIIWarningBanner.svelte -->
<!--
    Compact banner displayed above the message input when sensitive data (PII) is detected.

    Shows:
    - Lock icon + headline with the detection count ("2× sensitive data detected"),
      so users notice entries that are scrolled out of view in long drafts
    - One-line hint: highlights become placeholders; tap one to send the original
    - Small "Undo all" text link to keep every original value

    The whole banner preserves composer focus (data-preserve-composer-focus):
    tapping it must never collapse the open draft. The undo link prevents the
    pointer default so the editor keeps DOM focus (and the mobile keyboard).
-->
<script lang="ts">
    import { slide } from 'svelte/transition';
    import { text } from '@repo/ui';
    import type { PIIMatch } from './services/piiDetectionService';

    interface Props {
        /** List of detected PII matches */
        matches: PIIMatch[];
        /** Callback when user clicks "Undo all" */
        onUndoAll: () => void;
    }

    let { matches, onUndoAll }: Props = $props();

    let isVisible = $derived(matches.length > 0);
</script>

{#if isVisible}
    <div
        class="pii-warning-banner"
        data-testid="pii-warning-banner"
        data-preserve-composer-focus="true"
        transition:slide={{ duration: 200 }}
        role="alert"
        aria-live="polite"
    >
        <span class="clickable-icon icon_lock banner-icon" aria-hidden="true"></span>
        <div class="banner-text">
            <span class="banner-title" data-testid="banner-title">
                {$text('enter_message.pii.banner_title', { values: { count: matches.length } })}
            </span>
            <span class="banner-description" data-testid="banner-description">
                {$text('enter_message.pii.banner_description')}
            </span>
            <button
                type="button"
                class="undo-all-link"
                data-testid="undo-all-btn"
                title={$text('enter_message.pii.undo_all')}
                onpointerdown={(event) => event.preventDefault()}
                onmousedown={(event) => event.preventDefault()}
                onclick={onUndoAll}
            >
                {$text('enter_message.pii.undo_all_short')}
            </button>
        </div>
    </div>
{/if}

<style>
    .pii-warning-banner {
        display: flex;
        align-items: flex-start;
        gap: var(--spacing-4);
        padding: var(--spacing-3) var(--spacing-5);
        background-color: var(--color-warning-bg);
        border: 1px solid color-mix(in srgb, var(--color-warning) 35%, transparent);
        border-radius: var(--radius-3);
        margin-bottom: var(--spacing-3);
    }

    .banner-icon {
        width: 16px;
        height: 16px;
        margin-top: 1px;
        flex-shrink: 0;
        background: var(--color-warning);
        cursor: default;
    }

    .banner-text {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: var(--spacing-1);
        flex: 1;
        min-width: 0;
    }

    .banner-title {
        font-size: var(--font-size-xs);
        font-weight: 600;
        color: var(--color-font-primary);
        line-height: 1.3;
    }

    .banner-description {
        font-size: var(--font-size-xxs);
        font-weight: 500;
        color: var(--color-font-primary);
        opacity: 0.85;
        line-height: 1.35;
    }

    /* Text link, not a filled button: resets the global button styles. */
    .undo-all-link {
        all: unset;
        margin-top: var(--spacing-1);
        font-size: var(--font-size-xxs);
        font-weight: 600;
        line-height: 1.3;
        color: var(--color-warning);
        text-decoration: underline;
        text-underline-offset: 2px;
        cursor: pointer;
    }

    .undo-all-link:hover {
        opacity: 0.8;
    }

    .undo-all-link:focus-visible {
        outline: 2px solid var(--color-warning);
        outline-offset: 2px;
        border-radius: var(--radius-1);
    }
</style>
