<script lang="ts">
    import { externalLinks } from '../config/links';
    import { _ } from 'svelte-i18n';
</script>

<a
    href={externalLinks.discord}
    target="_blank"
    rel="noopener noreferrer"
    class="discord-button"
>
    <span class="small-icon icon_discord"></span>
    {$_('discord.join_server')}
</a>

<style>
    .small-icon.icon_discord {
        filter: brightness(0) invert(1);
    }
</style>