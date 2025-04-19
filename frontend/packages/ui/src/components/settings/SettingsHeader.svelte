<script lang="ts">
    import { get } from 'svelte/store';
    import { fly, fade, slide } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import { text } from '@repo/ui';
    import { panelState } from '../../stores/panelStateStore';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { tooltip } from '../../actions/tooltip';
    import { settingsNavigationStore } from '../../stores/settingsNavigationStore';

    // Variables for breadcrumb and navigation
    let navigationPath: string[] = [];
    let breadcrumbLabel = $text('settings.settings.text');
    let fullBreadcrumbLabel = '';
    let shortBreadcrumbLabel = '';
    let navButtonElement;
    let showSubmenuInfo = false;
    let navButtonLeft = false;
    let activeSubMenuIcon = '';
    let activeSubMenuTitle = '';
    let direction = 'forward';

    // Get help link from routes
    const baseHelpLink = getWebsiteUrl(routes.docs.userGuide_settings || '/docs/userguide/settings');
    let currentHelpLink = baseHelpLink;

    // Maximum width for breadcrumb text (in pixels)
    const MAX_BREADCRUMB_WIDTH = 220; // Adjusted to leave space for the back icon

    // Function to calculate the width of text with the correct font
    function getTextWidth(text, font = '14px "Lexend Deca Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif') {
        // Create a canvas element to measure text width
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        context.font = font;

        // Apply the font weight if needed for more accurate calculations
        if (window.getComputedStyle) {
            try {
                const style = window.getComputedStyle(document.body);
                const fontWeight = style.getPropertyValue('--font-weight-bold') || '700';
                context.font = `${fontWeight} ${font}`;
            } catch (e) {
                console.warn('Could not get computed style, using default font weight');
            }
        }

        const metrics = context.measureText(text);
        return metrics.width;
    }

    // Function to create optimal breadcrumb text that fits available space
    function createOptimalBreadcrumb(pathLabels) {
        // Save full breadcrumb first
        fullBreadcrumbLabel = pathLabels.join(' / ');

        // If full breadcrumb fits, use it
        if (getTextWidth(fullBreadcrumbLabel) <= MAX_BREADCRUMB_WIDTH) {
            return fullBreadcrumbLabel;
        }

        // If we only have one or two items, just use ellipsis + last item
        if (pathLabels.length <= 2) {
            return '... / ' + pathLabels[pathLabels.length - 1];
        }

        // Try different shortened versions
        let shortened = '';
        // Always include Settings (first element) and current path (last elements)
        // Try adding one more segment from the end each time
        for (let visibleSegments = 2; visibleSegments <= pathLabels.length; visibleSegments++) {
            const endSegments = pathLabels.slice(-visibleSegments);
            const candidateText = '... / ' + endSegments.join(' / ');

            if (getTextWidth(candidateText) <= MAX_BREADCRUMB_WIDTH) {
                shortened = candidateText;
            } else {
                // If this version doesn't fit, use previous version
                break;
            }
        }

        // If no shortened version fits, just show the last segment
        if (!shortened) {
            shortened = '... / ' + pathLabels[pathLabels.length - 1];
        }

        // Store the shortened version for tooltip
        shortBreadcrumbLabel = shortened;
        return shortened;
    }

    // Function to update breadcrumb label based on navigation path
    function updateBreadcrumbLabel() {
        if (navigationPath.length <= 0) {
            breadcrumbLabel = $text('settings.settings.text');
            fullBreadcrumbLabel = breadcrumbLabel;
            return;
        }

        // Create breadcrumb label with all path segments
        const pathLabels = [];

        // Always start with "Settings"
        pathLabels.push($text('settings.settings.text'));

        // Add each path segment's translated name (except the last one which is current view)
        for (let i = 0; i < navigationPath.length - 1; i++) {
            const segment = navigationPath[i];
            const translationKey = `settings.${segment}.text`;
            pathLabels.push($text(translationKey));
        }

        // Create optimal breadcrumb display that fits
        breadcrumbLabel = createOptimalBreadcrumb(pathLabels);
    }

    // Update breadcrumb on window resize
    function handleResize() {
        // Only update if we already have a navigation path
        if (navigationPath.length > 0) {
            updateBreadcrumbLabel();
        }
    }

    // Function to set active settings view with transitions (This will likely need to dispatch an event up)
    function handleOpenSettings(event) {
        const { settingsPath, direction: newDirection, icon, title } = event.detail;
        direction = newDirection;

        // Update the active view (This state should probably live higher up, maybe in Settings.svelte or a store)
        // For now, we'll update local state and dispatch an event
        // activeSettingsView = settingsPath; // Local state - might remove later
        activeSubMenuIcon = icon || '';
        activeSubMenuTitle = title || '';

        // Split the view path for breadcrumb navigation
        if (settingsPath !== 'main') {
            navigationPath = settingsPath.split('/');
            updateBreadcrumbLabel();
        } else {
            navigationPath = [];
            breadcrumbLabel = $text('settings.settings.text');
        }

        // Reset submenu info visibility
        showSubmenuInfo = false;
        navButtonLeft = false;

        // Update help link based on the active settings view
        if (settingsPath !== 'main') {
            // Handle nested paths in help links (replace / with -)
            const helpPath = settingsPath.replace('/', '-');
            currentHelpLink = `${baseHelpLink}/${helpPath}`;
            navButtonLeft = true;

            // Show left navigation and submenu info immediately for smooth transition
            showSubmenuInfo = true;
        } else {
            // Reset to base help link when returning to main view
            currentHelpLink = baseHelpLink;
        }

        // Dispatch event to parent to handle view change and profile container class
        dispatch('navigateSettings', { settingsPath, direction, icon, title });
    }

    // Enhanced back navigation - handle both main and nested views (This will likely need to dispatch an event up)
    function backToMainView() {
        if (navigationPath.length > 1) {
            // If we're in a nested view, go back one level
            const previousPath = navigationPath.slice(0, -1).join('/');

            direction = 'backward';
            handleOpenSettings({
                detail: {
                    settingsPath: previousPath,
                    direction: 'backward',
                    icon: navigationPath[0], // Use the first part as the icon
                    title: $text(`settings.${navigationPath[0]}.text`)
                }
            });
        } else {
            // If we're at the first level, go back to main
            direction = 'backward';
            // activeSettingsView = 'main'; // Local state - might remove later
            showSubmenuInfo = false;
            navButtonLeft = false;
            navigationPath = [];
            breadcrumbLabel = $text('settings.settings.text');

            // Reset help link to base when returning to main view
            currentHelpLink = baseHelpLink;

            // Dispatch event to parent to handle view change and profile container class
            dispatch('navigateSettings', { settingsPath: 'main', direction: 'backward' });
        }
    }

    // Need to dispatch close event to parent (Settings.svelte)
    import { createEventDispatcher, onMount } from 'svelte';
    const dispatch = createEventDispatcher();

    function handleCloseMenu() {
        panelState.closeSettings();
        // Also need to reset internal view state when closing
        resetInternalViewState();
        dispatch('closeSettings'); // Dispatch event to parent
    }

    // Helper function to reset internal view state when menu closes
    function resetInternalViewState() {
        // Reset the active view to main when closing the menu
        // activeSettingsView = 'main'; // Local state - might remove later
        navigationPath = [];
        breadcrumbLabel = $text('settings.settings.text');
        fullBreadcrumbLabel = '';
        shortBreadcrumbLabel = '';
        showSubmenuInfo = false;
        navButtonLeft = false;

        // Reset help link to base
        currentHelpLink = baseHelpLink;

        // Scroll to top when going back to main view (This should be handled by SettingsContent)
        // if (settingsContentElement) {
        //     settingsContentElement.scrollTop = 0;
        // }
    }


    // Setup listeners
    onMount(() => {
        window.addEventListener('resize', handleResize); // Keep for breadcrumb updates

        // Add listener for language changes
        const languageChangeHandler = () => {
            // Update breadcrumbs when language changes
            updateBreadcrumbLabel();
        };
        window.addEventListener('language-changed', languageChangeHandler);

        return () => {
            window.removeEventListener('resize', handleResize);
            window.removeEventListener('language-changed', languageChangeHandler);
        };
    });

    // Subscribe to both text and navigation store to handle language updates
    $: breadcrumbs = $settingsNavigationStore.breadcrumbs.map(crumb => ({
        ...crumb,
        // Apply translations to breadcrumb titles
        title: crumb.translationKey ? $text(crumb.translationKey + '.text') : crumb.title
    }));

    // Make breadcrumbLabel reactive to text store changes
    // Make breadcrumbLabel reactive to translation store changes
    $: {
        // Use $text store directly for reactivity
        if ($text && navigationPath) {
             updateBreadcrumbLabel();
        }
    }
</script>

<div class="settings-header">
     <div class="nav-button-container">
        {#if navButtonLeft}
            <button
                class="nav-button left"
                on:click={backToMainView}
                aria-label={$text('settings.back.text')}
                bind:this={navButtonElement}
            >
                <span class="icon icon_arrow_left"></span>
            </button>
        {/if}
    </div>

    <div
        id="settings-menu-title"
        class="breadcrumb-container"
        class:submenu-active={showSubmenuInfo}
        use:tooltip
        aria-label={fullBreadcrumbLabel}
    >
        {#if showSubmenuInfo}
            <span class="submenu-icon icon icon_{activeSubMenuIcon}"></span>
        {/if}
        <span class="breadcrumb-label">{breadcrumbLabel}</span>
    </div>

    <div class="nav-button-container right">
        <a
            href={currentHelpLink}
            target="_blank"
            rel="noopener noreferrer"
            class="nav-button right help-button"
            aria-label={$text('documentation.open_documentation.text')}
            use:tooltip
        >
            <span class="icon icon_help"></span>
        </a>
         <button
            class="nav-button right close-button"
            on:click={handleCloseMenu}
            aria-label={$text('activity.close.text')}
            use:tooltip
        >
            <span class="icon icon_close"></span>
        </button>
    </div>
</div>

<style>
    .settings-header {
        background-color: var(--color-grey-20);
        padding-bottom: 12px;
        position: sticky;
        top: 0;
        z-index: 10;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        display: flex;
        flex-direction: column;
        border-bottom: 1px solid var(--color-grey-30);
        position: relative;
        min-height: 30px;
    }

    .header-content {
        width: 100%;
        position: relative;
        transition: all 0.3s ease;
    }

    .settings-header.submenu-active {
        padding-bottom: 20px; /* Space for submenu info */
        transition: padding-bottom 0.3s ease; /* Smooth padding transition */
    }

    .nav-button-container {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 10px;
        position: relative;
        height: 40px; /* Give it a defined height */
    }

    .nav-button {
        all: unset;
        font-size: 14px;
        color: var(--color-grey-60);
        cursor: default;
        display: flex;
        align-items: center;
        padding: 4px 8px; /* Add padding for click area */
        transition: all 0.3s ease;
        pointer-events: none; /* Disable click interactions by default */
        max-width: calc(100% - 100px); /* Adjust max-width */
        border-radius: 4px; /* Add border radius */
    }

    .nav-button:hover {
        background-color: var(--color-grey-30); /* Add hover effect */
    }

    /* Add a span inside button to handle text overflow */
    .nav-button span {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        display: block;
    }

    .nav-button.left {
        cursor: pointer;
        pointer-events: all; /* Enable click interactions when in submenu */
    }

    .nav-button.right {
        pointer-events: all; /* Enable click interactions for help and close buttons */
        cursor: pointer;
    }

    .nav-button[aria-disabled="true"]:hover {
        cursor: default;
        background-color: transparent; /* No hover effect when disabled */
    }

    .breadcrumb-container {
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        font-weight: 600;
        color: var(--color-grey-90);
        display: flex;
        align-items: center;
        max-width: calc(100% - 120px); /* Adjust max-width */
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        transition: all 0.3s ease;
    }

    .breadcrumb-container.submenu-active {
        /* Adjust position when submenu info is shown */
        top: 60%;
    }

    .submenu-icon {
        margin-right: 8px;
        font-size: 20px; /* Adjust icon size */
    }

    .nav-button-container.right {
        display: flex;
        align-items: center;
        gap: 5px; /* Space between help and close buttons */
    }

    .help-button,
    .close-button {
        width: 24px; /* Fixed size for icon buttons */
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 4px; /* Add padding for click area */
    }

    .help-button .icon,
    .close-button .icon {
        font-size: 16px; /* Adjust icon size */
    }

    /* Styles for dimming the active chat container (These should be in Settings.svelte) */
    /*
    :global(.active-chat-container) {
        transition: opacity 0.3s ease;
    }

    :global(.active-chat-container.dimmed) {
        opacity: 0.3;
    }
    */

    /* Styles for adjusting chat container margin when settings is open (These should be in Settings.svelte) */
    /*
    :global(.chat-container) {
        transition: gap 0.3s ease;
    }

    @media (min-width: 1100px) {
        :global(.chat-container.menu-open) {
            gap: 20px;
        }
    }

    @media (max-width: 1099px) {
        :global(.chat-container.menu-open) {
            gap: 0px;
        }
    }
    */
</style>