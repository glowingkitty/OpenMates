<script lang="ts">
    import DiscordButton from './DiscordButton.svelte';
</script>

<div class="community-section">
    <div class="content">
        <h3>Community</h3>
        <!-- Community icon -->
        <div>
            <div class="main-icon icon_team"></div>
            <h2><mark>Join</mark> the development</h2>
        </div>

        <!-- Community text -->
        <p>
            OpenMates is a community effort. From software developers, to designers, 
            to users who are just excited about how AI can help them at work and in 
            everyday life - everyone can contribute in valuable ways.
        </p>
        <p class="join-text">
            For more infos, join us on Discord.
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