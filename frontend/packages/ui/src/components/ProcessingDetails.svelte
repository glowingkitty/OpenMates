<script lang="ts">
    import { _ } from 'svelte-i18n';  // Import translation function
    import Icon from './Icon.svelte'; // Import the Icon component

    // Define the possible types of processing details
    type ProcessingType = 'loaded_preferences' | 'using_apps' | 'started_focus';

    // Props using Svelte 5 runes
    let { 
        type,
        appNames = [],
        focusName = '',
        focusIcon = '',
        in_progress = false
    }: {
        type: ProcessingType;
        appNames?: string[];
        focusName?: string;
        focusIcon?: string;
        in_progress?: boolean;
    } = $props();

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
        <Icon name={appName} type="app" inline={true} element="span" />
    {/each}
    {#if focusName && focusIcon}
        <Icon name={focusIcon} type="focus" inline={true} element="span" />
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
