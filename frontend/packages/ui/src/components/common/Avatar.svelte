<!--
  Avatar component
  Displays a user avatar image with fallback to initials.
  Used in NavBar and user menus.
-->
<script lang="ts">
    /** Props for the Avatar component */
    interface Props {
        /** Username to display initials from as fallback */
        username?: string;
        /** URL of the avatar image */
        imageUrl?: string;
        /** Size variant: small (32px), medium (48px), large (64px) */
        size?: 'small' | 'medium' | 'large';
    }

    let { username = '', imageUrl = '', size = 'small' }: Props = $props();

    /** Whether the image failed to load (show initials fallback) */
    let imageError = $state(false);

    /** Get the first letter of the username as initials fallback */
    let initials = $derived(username ? username.charAt(0).toUpperCase() : '?');

    /** Whether to show the image (has URL and no load error) */
    let showImage = $derived(!!imageUrl && !imageError);

    /** Handle image load error — fall back to initials */
    function handleImageError() {
        imageError = true;
    }
</script>

<div class="avatar avatar-{size}" title={username}>
    {#if showImage}
        <img
            src={imageUrl}
            alt={username}
            class="avatar-image"
            onerror={handleImageError}
        />
    {:else}
        <span class="avatar-initials">{initials}</span>
    {/if}
</div>

<style>
    .avatar {
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        overflow: hidden;
        background-color: var(--color-primary, #6366f1);
        color: var(--color-text-on-primary, #ffffff);
        font-weight: 600;
        flex-shrink: 0;
    }

    .avatar-small {
        width: 32px;
        height: 32px;
        font-size: 14px;
    }

    .avatar-medium {
        width: 48px;
        height: 48px;
        font-size: 20px;
    }

    .avatar-large {
        width: 64px;
        height: 64px;
        font-size: 28px;
    }

    .avatar-image {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    .avatar-initials {
        user-select: none;
    }
</style>
