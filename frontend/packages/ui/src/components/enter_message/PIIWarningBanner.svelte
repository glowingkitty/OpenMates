<!-- frontend/packages/ui/src/components/enter_message/PIIWarningBanner.svelte -->
<!--
    Banner displayed above the message input when sensitive data (PII) is detected.
    
    Shows:
    - Warning message about detected sensitive data
    - Summary of what types were detected (e.g., "2 emails, 1 API key")
    - Explanation that data will be replaced with placeholders
    - "Undo All" button to restore all detected PII
    
    The banner slides in/out smoothly when PII is detected/cleared.
-->
<script lang="ts">
    import { slide } from 'svelte/transition';
    import { text } from '@repo/ui';
    import type { PIIMatch } from './services/piiDetectionService';
    import { createPIISummary } from './services/piiDetectionService';
    
    // Props
    interface Props {
        /** List of detected PII matches */
        matches: PIIMatch[];
        /** Callback when user clicks "Undo All" */
        onUndoAll: () => void;
    }
    
    let { matches, onUndoAll }: Props = $props();
    
    // Derived state
    let summary = $derived(createPIISummary(matches));
    let isVisible = $derived(matches.length > 0);
</script>

{#if isVisible}
    <div 
        class="pii-warning-banner"
        data-testid="pii-warning-banner"
        transition:slide={{ duration: 200 }}
        role="alert"
        aria-live="polite"
    >
        <div class="banner-content">
            <span class="clickable-icon icon_shield_lock banner-icon"></span>
            <div class="banner-text">
                <span class="banner-title" data-testid="banner-title">
                    {$text('enter_message.pii.banner_title')}
                </span>
                <span class="banner-description" data-testid="banner-description">
                    Found {summary}. These will be replaced with placeholders before sending. Click on highlighted text to keep original.
                </span>
            </div>
            <button
                class="undo-all-btn"
                data-testid="undo-all-btn"
                onclick={onUndoAll}
                title={$text('enter_message.pii.undo_all')}
            >
                {$text('enter_message.pii.undo_all_short')}
            </button>
        </div>
    </div>
{/if}

<style>
    .pii-warning-banner {
        display: flex;
        align-items: center;
        padding: var(--spacing-4) var(--spacing-6);
        background-color: var(--color-warning-bg, rgba(255, 193, 7, 0.15));
        border: 1px solid var(--color-warning-border, rgba(255, 193, 7, 0.3));
        border-radius: var(--radius-3);
        margin-bottom: var(--spacing-4);
    }
    
    .banner-content {
        display: flex;
        align-items: center;
        gap: var(--spacing-5);
        width: 100%;
    }
    
    .banner-icon {
        width: 20px;
        height: 20px;
        flex-shrink: 0;
        background: var(--color-warning, #f59e0b);
    }
    
    .banner-text {
        display: flex;
        flex-direction: column;
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
        font-weight: 400;
        color: var(--color-grey-60);
        line-height: 1.4;
    }
    
    .undo-all-btn {
        flex-shrink: 0;
        padding: var(--spacing-3) var(--spacing-6);
        border-radius: var(--radius-2);
        font-size: var(--font-size-xxs);
        font-weight: 600;
        cursor: pointer;
        transition: background-color var(--duration-fast) var(--easing-default);
        border: 1px solid var(--color-grey-30);
        background-color: var(--color-grey-10);
        color: var(--color-font-primary);
    }
    
    .undo-all-btn:hover {
        background-color: var(--color-grey-20);
    }
    
    .undo-all-btn:active {
        background-color: var(--color-grey-30);
    }
    
    /* Mobile responsiveness */
    @media (max-width: 480px) {
        .pii-warning-banner {
            padding: var(--spacing-3) var(--spacing-5);
        }
        
        .banner-content {
            flex-wrap: wrap;
            gap: var(--spacing-3);
        }
        
        .banner-text {
            flex-basis: calc(100% - 30px);
        }
        
        .undo-all-btn {
            margin-left: auto;
        }
    }
</style>
