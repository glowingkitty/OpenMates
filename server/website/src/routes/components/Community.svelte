<script lang="ts">
    import DiscordButton from './DiscordButton.svelte';
    import { _ } from 'svelte-i18n';
</script>

<div class="community-section">
    <div class="content">
        <h3>{$_('community.heading.text')}</h3>
        <!-- Community icon -->
        <div>
            <div class="main-icon icon_team"></div>
            <h2><mark>{$_('community.join_development_1.text')}</mark> {$_('community.join_development_2.text')}</h2>
        </div>

        <!-- Community text -->
        <p>
            {$_('community.description.text')}
        </p>
        <p class="join-text">
            {$_('community.join_discord.text')}
        </p>

        <!-- Discord button -->
        <div class="button-wrapper">
            <DiscordButton />
        </div>
    </div>
</div>

<style>

    .main-icon {
        width: 96px;
        height: 96px;
        margin: 0 auto 1.5rem;
        mask-size: cover;
        mask-repeat: no-repeat;
        background: var(--color-primary);
    }

    @media (max-width: 600px) {
        .main-icon {
            width: 67.2px;
            height: 67.2px;
        }
    }

    .main-icon.icon_team {
        mask-image: url('/icons/team.svg');
    }

    .community-section {
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 4rem 1rem;
        background-color: var(--color-background);
    }

    .content {
        max-width: 600px;
        text-align: center;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 1.5rem;
    }

    p {
        color: var(--color-text-secondary);
        margin: 0;
    }

    .join-text {
        margin-top: -0.5rem;
    }

    .button-wrapper {
        margin-top: 0.5rem;
    }

</style> 