<script lang="ts">
    import DiscordButton from './DiscordButton.svelte';
    import Icon from './Icon.svelte';
</script>

<div class="community-section">
    <div class="content">
        <!-- Community icon -->
        <div class="icon-wrapper">
            <Icon name="team" type="default" />
        </div>

        <!-- Community text -->
        <h2>Community</h2>
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

    .icon-wrapper {
        margin-bottom: 1rem;
    }

    h2 {
        font-size: 2rem;
        font-weight: 600;
        margin: 0;
        color: var(--color-text);
    }

    p {
        font-size: 1.1rem;
        line-height: 1.6;
        color: var(--color-text-secondary);
        margin: 0;
    }

    .join-text {
        font-size: 1rem;
        margin-top: -0.5rem;
    }

    .button-wrapper {
        margin-top: 0.5rem;
    }

    /* Responsive adjustments */
    @media (max-width: 768px) {
        .community-section {
            padding: 3rem 1rem;
        }

        .content {
            max-width: 90%;
        }

        h2 {
            font-size: 1.75rem;
        }

        p {
            font-size: 1rem;
        }
    }
</style> 