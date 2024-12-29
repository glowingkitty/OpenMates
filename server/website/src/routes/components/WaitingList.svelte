<script lang="ts">
    import DiscordButton from './DiscordButton.svelte';
</script>

<div class="waiting-list-section">
    <div class="content-wrapper">
        <div class="discord-content">
            <p class="discord-text">Members in our Discord will<br><mark><bold>get early access.</bold></mark></p>
            <DiscordButton />
        </div>
    </div>

    <p class="invites-text">
        <span class="calendar-icon"></span>
        First invites in Jan/Feb 2025
    </p>
</div>

<style>
    .waiting-list-section {
        width: 420px;
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
        color: #666;
        margin: 0;
        text-align: center;
    }

    .invites-text {
        color: #888;
        margin-top: 0;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .calendar-icon {
        display: inline-block;
        filter: opacity(40%);
        vertical-align: middle;
    }
</style>