<script lang="ts">
    import Icon from './Icon.svelte';
</script>

<div class="container">
    <div class="icon-wrapper">
        <Icon name="events" type="app" />
    </div>
</div>

<style>
    @import '../lib/styles/icons.css';
    .container {
        display: flex;
        min-height: 100vh;
        padding: 20px;
    }

    .icon-wrapper {
        /* Position on the left side */
        position: fixed;
        left: 40px;
        top: 40px;
    }
</style>
