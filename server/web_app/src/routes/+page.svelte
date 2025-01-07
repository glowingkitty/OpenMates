<script>
    // Import the required components
    import ActivityHistory from '@website-components/ActivityHistory.svelte';
    import ActiveChat from '@website-components/ActiveChat.svelte';
</script>

<div class="sidebar">
    <ActivityHistory />
</div>

<div class="main-content">
    <ActiveChat />
</div>

<style>
    :root {
        --sidebar-width: 325px;
        --sidebar-margin: 20px;
    }
    .sidebar {
        /* Fixed positioning relative to viewport */
        position: fixed;
        left: 0;
        top: 0;
        bottom: 0;

        /* Specified width */
        width: var(--sidebar-width);

        /* Background color */
        background-color: var(--color-grey-20);

        /* Ensure sidebar stays above other content */
        z-index: 10;

        /* Add scrolling for overflow content */
        overflow-y: auto;
    }

    .main-content {
        /* Position relative to accommodate fixed sidebar */
        position: fixed;
        left: calc(var(--sidebar-width) + var(--sidebar-margin)); /* sidebar width + 15px margin */
        top: 110px;
        right: var(--sidebar-margin);
        bottom: var(--sidebar-margin);

        /* Add scrolling for overflow content */
        overflow-y: auto;
    }
</style>
