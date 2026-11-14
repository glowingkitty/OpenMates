<!--
  Why a signed-out visitor sees Sign up / Log in instead of Send.
  The signed-out composer never shows a disabled Send; when it cannot send it
  shows the account button plus this one-line reason (guestComposerState.ts).
-->
<script lang="ts">
    import { fade } from 'svelte/transition';
    import { text } from '@repo/ui';
    import { GUEST_ACCESS_REASON_KEYS, type GuestAccessReason } from './guestComposerState';

    interface Props {
        reason: GuestAccessReason;
    }

    let { reason }: Props = $props();
</script>

<div class="guest-access-reason" data-testid="guest-access-reason" data-reason={reason} role="status" transition:fade={{ duration: 160 }}>
    {$text(`enter_message.${GUEST_ACCESS_REASON_KEYS[reason]}`)}
</div>

<style>
    .guest-access-reason {
        margin: 0 8px var(--spacing-2, 6px);
        padding: var(--spacing-2, 6px) var(--spacing-4, 12px);
        border: 1px solid var(--color-grey-30);
        border-radius: var(--radius-4, 12px);
        background: var(--color-grey-0);
        color: var(--color-font-secondary);
        font-size: var(--font-size-xs);
        line-height: 1.35;
        text-align: center;
    }
</style>
