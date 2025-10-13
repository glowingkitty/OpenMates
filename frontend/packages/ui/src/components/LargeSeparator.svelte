<script lang="ts">
    // Props using Svelte 5 runes
    let { 
        reverse_direction = false,
        after_header = false
    }: {
        reverse_direction?: boolean;
        after_header?: boolean;
    } = $props();
</script>

<div class="large-separator {reverse_direction ? 'rotate' : ''} {after_header ? 'after_header' : ''}">
    <div class="separator-content"></div>
</div>

<style>
    /* Main separator class with repeating pattern */
    .large-separator {
        width: 100%;
        height: 132px;
        position: relative;
        /* Control the repetition pattern */
        background-image: url('@openmates/ui/static/seperator_block.svg');
        background-repeat: repeat-x;
        background-size: 42px 100%;
        /* Center the pattern horizontally and vertically */
        background-position: calc(50% - 21px) center;
        -webkit-background-size: 42px 100%;
        z-index: -1;
    }

    /* Add filter inversion for dark mode */
    :global([data-theme="dark"]) .large-separator {
        filter: invert(1);
    }

    .large-separator.rotate {
        rotate: 180deg;
    }

    .large-separator.after_header{
        top: -120px;
        margin-bottom: -120px;
    }
</style>