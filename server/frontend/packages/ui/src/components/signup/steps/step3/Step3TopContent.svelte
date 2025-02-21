<script lang="ts">
    import { _ } from 'svelte-i18n';
    import { processedImageUrl } from '../../../../stores/profileImage';
    export let username: string;
</script>

<div class="content">
    <h2>{$_('chat.welcome.hey.text')} {username}</h2>
    <div class="image-circle">
        {#if $processedImageUrl}
            <img src={$processedImageUrl} alt="Profile preview" class="preview-image" />
        {:else}
            <div class="clickable-icon icon_image"></div>
        {/if}
    </div>
</div>

<style>
    .content {
        padding: 24px;
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 24px;
    }

    .image-circle {
        width: 170px;
        height: 170px;
        border-radius: 50%;
        background-color: var(--color-grey-10);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        display: flex;
        justify-content: center;
        align-items: center;
    }

    .image-circle :global(.clickable-icon) {
        width: 75px;
        height: 75px;
        opacity: 0.5;
        cursor: unset;
    }

    .preview-image {
        width: 100%;
        height: 100%;
        border-radius: 50%;
        object-fit: cover;
    }
</style>
