<!--
  Chat processing status shown above the message composer.
  This mechanical extraction preserves the existing text-only typing indicator.
  Mate identity rendering and click handling are intentionally deferred to the
  processing-feedback UI change that consumes this component.
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
    let {
        lines,
        statusType = null,
    }: ChatProcessingIndicatorProps = $props();
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
            <span class={index === 0 ? 'indicator-primary-line' : index === 1 ? 'indicator-secondary-line' : 'indicator-tertiary-line'}>{line}</span>
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

    .typing-indicator.status-typing span,
    .typing-indicator.status-processing span {
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

    @keyframes typing-indicator-shimmer {
        0% {
            background-position: 200% 0;
        }
        100% {
            background-position: -200% 0;
        }
    }
</style>
