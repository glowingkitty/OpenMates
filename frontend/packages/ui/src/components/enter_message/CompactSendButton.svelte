<script lang="ts">
    import { text } from '@repo/ui';

    interface Props {
        onclick: (event: MouseEvent) => void;
        disabled?: boolean;
        busy?: boolean;
        floating?: boolean;
        testId?: string;
    }

    let { onclick, disabled = false, busy = false, floating = false, testId = 'composer-send-button' }: Props = $props();
</script>

<button
    type="button"
    class="minimized-send-button"
    class:floating
    data-testid={testId}
    data-preserve-composer-focus="true"
    aria-label={$text('enter_message.send')}
    {disabled}
    aria-busy={busy}
    {onclick}
>
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none">
        <path d="M12 19V5m0 0-6 6m6-6 6 6" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
</button>

<style>
    /* Shared with recording: preserve the existing minimized composer Send. */
    .minimized-send-button {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 40px;
        min-width: 0;
        height: 40px;
        flex-shrink: 0;
        padding: 0;
        border: 0;
        border-radius: 50%;
        color: var(--color-font-button);
        background: var(--color-button-primary);
        cursor: pointer;
    }

    .floating {
        position: absolute;
        z-index: 12;
        right: var(--spacing-6);
        top: 50%;
        transform: translateY(-50%);
    }

    svg { width: 20px; height: 20px; }
    button:hover { background: var(--color-button-primary-hover); }
    button:active { background: var(--color-button-primary-pressed); }
    button:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 3px; }
</style>
