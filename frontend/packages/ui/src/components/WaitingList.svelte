<script lang="ts">
    import InstagramButton from './InstagramButton.svelte';
    import MastodonButton from './MastodonButton.svelte';
    import { text } from '@repo/ui';

    // Props using Svelte 5 runes mode
    let { showPersonalInviteMessage = false }: { showPersonalInviteMessage?: boolean } = $props();
</script>

<div class="waiting-list-section">
    <div class="content-wrapper">
        <div class="discord-content">
            <p class="discord-text">
                {#if showPersonalInviteMessage}
                <mark><bold>{$text('signup.dont_have_personal_invite_code.text')}</bold></mark><br>
                {/if}
                {@html $text('signup.follow_us.text')}
            </p>
            <InstagramButton />
            <MastodonButton />
        </div>
    </div>

    
</div>

<style>
    .waiting-list-section {
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.5rem;
        margin-top: 2rem;
    }

    @media (max-width: 600px) {
        .waiting-list-section {
            margin-top: 0px;
        }
    }

    .content-wrapper {
        width: 100%;
        min-height: 120px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .discord-content {
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 1rem;
    }

    .discord-text {
        color: var(--color-grey-60);
        margin: 0;
        text-align: center;
    }
</style>