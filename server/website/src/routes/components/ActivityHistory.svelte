<script>
    import { _ } from 'svelte-i18n'; // Import the translation function
</script>

<button 
    class="clickable-icon icon_search top-button left" 
    aria-label={$_('activity.search.text')}
></button>
<button 
    class="clickable-icon icon_filter top-button center" 
    aria-label={$_('activity.filter.text')}
></button>
<button 
    class="clickable-icon icon_close top-button right" 
    aria-label={$_('activity.close.text')}
></button>

<style>
    /* Position buttons in the top bar */
    .top-button {
        position: absolute;
        top: 20px;
    }

    .top-button.left {
        left: 20px;
    }

    .top-button.center {
        left: 50%;
        transform: translateX(-50%); /* Center the button horizontally */
    }

    .top-button.right {
        right: 20px;
    }
</style>