<!--
  Chat processing status shown above the message composer.
  It preserves text-only selection until current-turn mate metadata is known.
  Known mates use existing metadata, portrait styling, and localized labels.
  The name action delegates navigation to the owning chat component.
-->
<script module lang="ts">
    export type ChatProcessingIndicatorProps = {
        lines: string[];
        mateCategory?: string | null;
        statusType?: string | null;
        onMateClick?: () => void;
    };
</script>

<script lang="ts">
    import { text } from '@repo/ui';
    import { getMatesById } from '../data/matesMetadata';

    let {
        lines,
        mateCategory = null,
        statusType = null,
        onMateClick = undefined,
    }: ChatProcessingIndicatorProps = $props();

    const matesById = getMatesById();
    let selectedMateName = $derived(
        mateCategory && mateCategory !== 'openmates_official' && matesById[mateCategory]
            ? $text(`mates.${mateCategory}`)
            : null
    );
    let nameOffset = $derived(selectedMateName ? (lines[0] ?? '').indexOf(selectedMateName) : -1);
</script>

{#if lines.length > 0}
    <div
        class="typing-indicator"
        data-testid="chat-processing-indicator"
        class:status-sending={statusType === 'sending'}
        class:status-processing={statusType === 'processing'}
        class:status-typing={statusType === 'typing'}
    >
        {#each lines as line, index}
            {#if index === 0 && selectedMateName}
                <div class="selected-mate-status" data-testid="chat-processing-selected-mate">
                    <div
                        class="mate-profile {mateCategory} chat-processing-mate-avatar"
                        data-testid="chat-processing-mate-avatar"
                        data-mate-category={mateCategory}
                        aria-hidden="true"
                    >
                        <span class="chat-processing-ai-badge" data-testid="chat-processing-ai-badge"></span>
                    </div>
                    <span class="indicator-primary-line indicator-status-line">
                        {#if onMateClick && nameOffset >= 0}
                            {line.slice(0, nameOffset)}<button
                                type="button"
                                class="indicator-primary-action"
                                data-testid="chat-processing-mate-name"
                                onclick={onMateClick}
                            >{selectedMateName}</button>{line.slice(nameOffset + selectedMateName.length)}
                        {:else}
                            {line}
                        {/if}
                    </span>
                </div>
            {:else}
                <span class="indicator-status-line {index === 0 ? 'indicator-primary-line' : index === 1 ? 'indicator-secondary-line' : 'indicator-tertiary-line'}">{line}</span>
            {/if}
        {/each}
    </div>
{/if}

<style>
    .typing-indicator {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: flex-end;
        gap: var(--spacing-1);
        text-align: center;
        font-size: 1rem;
        color: var(--color-grey-60);
        padding: var(--spacing-0) var(--spacing-8) var(--spacing-3);
        font-style: italic;
        background: linear-gradient(
            to bottom,
            transparent 0%,
            transparent 14%,
            var(--color-grey-20) 56%,
            var(--color-grey-20) 100%
        );
        position: relative;
        z-index: var(--z-index-raised);
    }

    .indicator-primary-line {
        font-size: 1rem;
    }

    .selected-mate-status {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: var(--spacing-2);
        max-width: 100%;
    }

    :global(.mate-profile.chat-processing-mate-avatar) {
        width: 2rem;
        height: 2rem;
        margin: 0;
        opacity: 1;
        animation: none;
        overflow: visible;
        flex-shrink: 0;
    }

    :global(.mate-profile.chat-processing-mate-avatar)::before,
    :global(.mate-profile.chat-processing-mate-avatar)::after {
        display: none;
    }

    .chat-processing-ai-badge {
        position: absolute;
        inset-inline-end: -0.2rem;
        bottom: -0.2rem;
        width: 0.875rem;
        height: 0.875rem;
        border-radius: var(--radius-full);
        background-color: var(--color-grey-0);
        box-shadow: var(--shadow-xs);
        z-index: 1;
    }

    .chat-processing-ai-badge::after {
        content: '';
        position: absolute;
        inset: 0.1875rem;
        background: var(--color-primary);
        -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
        mask-image: url('@openmates/ui/static/icons/ai.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
    }

    .indicator-primary-action {
        border: 0;
        padding: 0;
        background: transparent;
        color: inherit;
        font: inherit;
        font-style: inherit;
        cursor: pointer;
    }

    .indicator-primary-action:hover,
    .indicator-primary-action:focus-visible {
        text-decoration: underline;
        text-underline-offset: 0.15em;
    }

    .indicator-secondary-line {
        font-size: 0.7rem;
        opacity: 0.8;
    }

    .indicator-tertiary-line {
        font-size: 0.65rem;
        opacity: 0.65;
    }

    .typing-indicator.status-processing,
    .typing-indicator.status-typing {
        color: var(--color-grey-50);
    }

    .typing-indicator.status-typing .indicator-status-line,
    .typing-indicator.status-typing .indicator-primary-action,
    .typing-indicator.status-processing .indicator-status-line,
    .typing-indicator.status-processing .indicator-primary-action {
        background: linear-gradient(
            90deg,
            var(--color-grey-60) 0%,
            var(--color-grey-60) 40%,
            var(--color-grey-40) 50%,
            var(--color-grey-60) 60%,
            var(--color-grey-60) 100%
        );
        background-size: 200% 100%;
        background-clip: text;
        -webkit-background-clip: text;
        color: transparent;
        animation: typing-indicator-shimmer 1.5s infinite linear;
    }

    @media (prefers-reduced-motion: reduce) {
        .typing-indicator.status-typing .indicator-status-line,
        .typing-indicator.status-typing .indicator-primary-action,
        .typing-indicator.status-processing .indicator-status-line,
        .typing-indicator.status-processing .indicator-primary-action {
            animation: none;
        }
    }

    @keyframes typing-indicator-shimmer {
        0% {
            background-position: 200% 0;
        }
        100% {
            background-position: -200% 0;
        }
    }
</style>
