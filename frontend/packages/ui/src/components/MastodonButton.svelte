<script lang="ts">
    import { externalLinks } from '../config/links';
    import { text } from '@repo/ui';
</script>

<a
    href={externalLinks.mastodon}
    target="_blank"
    rel="noopener noreferrer"
    class="mastodon-button"
>
    <span class="small-icon icon_mastodon"></span>
    {@html $text('signup.open_mastodon.text')}
</a>

<style>
    .small-icon.icon_mastodon {
        filter: brightness(0) invert(1);
    }
</style>