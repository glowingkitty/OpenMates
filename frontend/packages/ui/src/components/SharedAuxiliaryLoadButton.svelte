<script lang="ts">
    import { text } from '@repo/ui';

    let { loading = false, failed = false, testId = 'shared-auxiliary-load-more', onLoad }: {
        loading?: boolean;
        failed?: boolean;
        testId?: string;
        onLoad: () => void;
    } = $props();
</script>

<button
    type="button"
    data-testid={testId}
    aria-busy={loading}
    disabled={loading}
    onclick={onLoad}
>
    {failed ? $text('common.try_again') : $text('chats.loadMore.button')}
</button>

<style>
    button {
        min-width: unset;
        height: auto;
        padding: var(--spacing-2) var(--spacing-4);
        border: 1px solid var(--color-grey-30);
        border-radius: var(--border-radius-full);
        background: var(--color-grey-10);
        color: var(--color-grey-80);
        cursor: pointer;
    }

    button:focus-visible {
        outline: 2px solid var(--color-primary);
        outline-offset: 2px;
    }

    button:disabled { opacity: 0.65; cursor: wait; }
</style>
