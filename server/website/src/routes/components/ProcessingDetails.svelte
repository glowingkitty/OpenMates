<script lang="ts">
    import { _ } from 'svelte-i18n';  // Import translation function

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
                return $_('chat_examples.processing.status.loaded.text');
            case 'started_focus':
                return $_('chat_examples.processing.status.started.text');
            case 'using_apps':
                return inProgress 
                    ? $_('chat_examples.processing.status.using.text')
                    : $_('chat_examples.processing.status.used.text');
            default:
                return '';
        }
    };

    // Helper function to get the detail text based on type
    const getDetailText = (type: ProcessingType): string => {
        switch (type) {
            case 'loaded_preferences':
                return $_('chat_examples.processing.details.preferences.text');
            case 'started_focus':
                return focusName;
            case 'using_apps':
                return appNames.length > 1 
                    ? $_('chat_examples.processing.details.apps.text')
                    : $_('chat_examples.processing.details.app.text');
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

    /* dark mode */
    :global([data-theme="dark"]) .processing-details::after {
        filter: invert(0.6);
    }
</style>
