<!--
    ForkProgressBanner Component

    A slim banner shown at the top of the source chat's message area
    while a fork operation is in progress. It shows a progress percentage
    and disappears automatically when the fork completes.

    Rendered by ActiveChat.svelte when isForkingChat(activeChatId) is true.
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import { forkProgressStore } from '../../stores/forkProgressStore';

    // ---------------------------------------------------------------------------
    // State (from global fork progress store)
    // ---------------------------------------------------------------------------

    let forkState = $derived($forkProgressStore);
    let progress = $derived(forkState.progress);
</script>

<div class="fork-banner" role="status" aria-live="polite">
    <div class="fork-banner-icon icon_fork"></div>
    <span class="fork-banner-text">
        {$text('chats.fork.forking_banner')}
    </span>
    <span class="fork-banner-progress">{progress}%</span>
    <div class="fork-banner-track">
        <div class="fork-banner-fill" style="width: {progress}%"></div>
    </div>
</div>

<style>
    .fork-banner {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
        padding: var(--spacing-4) var(--spacing-8);
        background: var(--color-primary-muted, rgba(79, 142, 247, 0.12));
        border-bottom: 1px solid var(--color-primary-border, rgba(79, 142, 247, 0.2));
        font-size: var(--font-size-xs);
        color: var(--color-text-secondary, #8a9bb0);
        position: relative;
        overflow: hidden;
    }

    /* Optional icon — uses existing CSS icon system. Falls back gracefully if not defined. */
    .fork-banner-icon {
        width: 14px;
        height: 14px;
        flex-shrink: 0;
        background-color: var(--color-primary, #4f8ef7);
        mask-image: var(--icon-fork, none);
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
    }

    .fork-banner-text {
        flex: 1;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .fork-banner-progress {
        font-variant-numeric: tabular-nums;
        font-weight: 600;
        color: var(--color-primary, #4f8ef7);
        flex-shrink: 0;
    }

    /* Slim inline progress track inside the banner */
    .fork-banner-track {
        position: absolute;
        bottom: 0;
        left: 0;
        width: 100%;
        height: 2px;
        background: transparent;
    }

    .fork-banner-fill {
        height: 100%;
        background: var(--color-primary, #4f8ef7);
        transition: width 0.4s ease;
    }
</style>
