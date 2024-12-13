<script lang="ts">
    // Define the possible types of processing details
    type ProcessingType = 'loading_preferences' | 'using_app' | 'used_apps';

    // Props for the component
    export let type: ProcessingType;
    export let appNames: string[] = []; // For single app or multiple apps

    // Helper function to get lowercase version for CSS class
    const getCssClassName = (appName: string): string => appName.toLowerCase();
</script>

{#if type === 'loading_preferences'}
    <button class="processing-details">
        <span class="icon app-{getCssClassName(appNames[0])} inline"></span>
        Loading {appNames[0]} <strong>preferences</strong> ...
    </button>
{:else if type === 'using_app'}
    <button class="processing-details">
        <span class="icon app-{getCssClassName(appNames[0])} inline"></span>
        Using <strong>{appNames[0]}</strong> app ...
    </button>
{:else if type === 'used_apps'}
    <button class="processing-details">
        {#each appNames as appName}
            <span class="icon app-{getCssClassName(appName)} inline"></span>
        {/each}
        Used <strong>{appNames.length} apps</strong> ...
    </button>
{/if}
