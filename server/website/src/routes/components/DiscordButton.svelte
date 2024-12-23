<script lang="ts">
    import { externalLinks } from '$lib/config/links';
</script>

<a
    href={externalLinks.discord}
    target="_blank"
    rel="noopener noreferrer"
    class="discord-button"
>
    <span class="small-icon icon_discord"></span>
    Join server
</a>

<style>
    .small-icon.icon_discord {
        filter: brightness(0) invert(1);
    }
</style>