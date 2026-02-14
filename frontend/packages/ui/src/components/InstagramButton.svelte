<script lang="ts">
    import { externalLinks } from '../config/links';
    import { text } from '@repo/ui';
</script>

<a
    href={externalLinks.instagram}
    target="_blank"
    rel="noopener noreferrer"
    class="instagram-button"
>
    <span class="small-icon icon_instagram"></span>
    {@html $text('signup.open_instagram')}
</a>

<style>
    .small-icon.icon_instagram {
        filter: brightness(0) invert(1);
    }
</style>