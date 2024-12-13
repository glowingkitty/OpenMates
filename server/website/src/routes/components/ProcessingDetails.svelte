<script lang="ts">
    // Define the possible types of processing details
    type ProcessingType = 'loaded_preferences' | 'using_apps' | 'started_focus';

    // Props for the component
    export let type: ProcessingType;
    export let appNames: string[] = []; // For single app or multiple apps
    export let focusName: string = ''; // For single focus
    export let focusIcon: string = ''; // For single focus
    export let in_progress: boolean = false; // For controlling "Using" vs "Used" status

    // Helper function to get lowercase version for CSS class
    const getCssClassName = (appName: string): string => appName.toLowerCase();

    // Helper function to get the status text based on type and progress
    const getStatusText = (type: ProcessingType, inProgress: boolean): string => {
        switch (type) {
            case 'loaded_preferences':
                return 'Loaded';
            case 'started_focus':
                return 'Started';
            case 'using_apps':
                return inProgress ? 'Using' : 'Used';
            default:
                return '';
        }
    };

    // Helper function to get the detail text based on type
    const getDetailText = (type: ProcessingType): string => {
        switch (type) {
            case 'loaded_preferences':
                return 'preferences';
            case 'started_focus':
                return focusName;
            case 'using_apps':
                return appNames.length > 1 ? `apps` : 'app';
            default:
                return '';
        }
    };
</script>

<button class="processing-details">
    {getStatusText(type, in_progress)}
    {#each appNames as appName}
        <span class="icon app-{getCssClassName(appName)} inline"></span>
    {/each}
    {#if focusName}
        <span class="icon focus-{getCssClassName(focusIcon)} focus-icon inline"></span>
    {/if}
    <strong>{getDetailText(type)}</strong>
    {#if in_progress}...{/if}
</button>

<style>
    /* Add any specific styling needed */
    .processing-details {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
</style>
