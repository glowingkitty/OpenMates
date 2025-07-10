<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_6_bottom_content_svelte:
    enter_app_name_input_field:
        type: 'input_field'
        placeholder: $text('signup.click_to_enter_app_name.text')
        purpose:
            - 'User can enter / search for the name of the 2FA app they use.'
        processing:
            - 'User clicks field'
            - 'Once clicked, a search results field pops up above the input field (not blocking the view of the field) with default 2FA apps.'
            - 'User starts typing the name of the 2FA app they use.'
            - 'Continue button is shown under the input field.'
            - 'Search results are filtered based on the user input, while the user types.'
            - 'If no search results, Safety tip is shown in search results field instead.'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
        connected_documentation:
            - '/signup/2fa-reminder'
    tfa_apps_search_results_block:
        type: 'search_results'
        text:
            - $text('signup.safety_tip.text')
            - $text('signup.separate_2fa_app.text')
        purpose:
            - 'Shows search results for 2FA apps, based on user input. Or, if no search results, shows safety tip.'
        processing:
            - 'Search results are shown based on user input.'
            - 'If no search results, Safety tip is shown.'
            - 'User can click on a search result to select it and close the search results field.'
            - 'If user clicks outside the search results field, the field closes.'
            - 'If user clicks on search result, the selected 2FA app is shown in the input field and in topcontent preview of 2fa processing during login.'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
        connected_documentation:
            - '/signup/2fa-reminder'
    continue_button:
        type: 'button'
        text: $text('signup.continue.text')
        purpose:
            - 'User clicks to continue to the next step of the signup process.'
        processing:
            - 'Only visible if user has entered a 2FA app name.'
            - 'User clicks the button'
            - 'If user has entered a 2FA app name, the name is saved to the user account.'
            - 'User is taken to the next step of the signup process.'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
        connected_documentation:
            - '/signup/2fa-reminder'
-->

<script lang="ts">
    import { text } from '@repo/ui'; // Assuming this path resolves correctly despite lint error
    import { onMount } from 'svelte';
    import { createEventDispatcher } from 'svelte';
    import { tfaApps, tfaAppIcons } from '../../../../config/tfa';
    import { authStore } from '../../../../stores/authStore'; // Import authStore
    import { userDB } from '../../../../services/userDB'; // Import userDB
    import InputWarning from '../../../common/InputWarning.svelte'; // Import InputWarning

    // Accept selected app from parent
    export let selectedAppName: string | null = null;
    
    let appName = '';
    let appInput: HTMLInputElement;
    const dispatch = createEventDispatcher();
    let showSearchResults = false;
    let searchResults = tfaApps;
    let selectedApp = '';
    let isLoading = true; // Track loading state
    let initialtfa_app_name: string | null = null; // Store the initial app name loaded
    let errorMessage = ''; // To display errors
    let continueButtonElement: HTMLButtonElement; // Add variable for button ref

    // Load initial state from IndexedDB and initialize from selectedAppName prop
    onMount(async () => {
        isLoading = true;
        errorMessage = '';
        try {
            await userDB.init(); // Ensure DB is initialized
            const userData = await userDB.getUserData();
            initialtfa_app_name = userData?.tfa_app_name || selectedAppName; // Store initial name

            if (initialtfa_app_name) {
                appName = initialtfa_app_name; // Set current input value
                // Check if it's one of the predefined apps
                if (tfaApps.includes(initialtfa_app_name)) {
                    selectedApp = initialtfa_app_name;
                }
                // Dispatch event to ensure parent knows this app is selected/loaded initially
                dispatch('selectedApp', { appName: initialtfa_app_name });
            }
        } catch (error) {
            console.error("Error loading tfa_app_name from DB:", error);
            errorMessage = "Failed to load saved app name."; // Inform user
        } finally {
            isLoading = false;
        }
    });

    // Reactive statement to determine button visibility
    $: showContinueButton =
        !isLoading &&
        appName.trim().length >= 3 &&
        appName.trim().length <= 40 &&
        appName.trim() !== (initialtfa_app_name || ''); // Show only if valid length AND different from initial

    function handleInput(event: Event) {
        errorMessage = ''; // Clear error on input
        const input = event.target as HTMLInputElement;
        appName = input.value;
        showSearchResults = true;
        searchResults = appName ? tfaApps.filter(app => app.toLowerCase().includes(appName.toLowerCase())) : tfaApps;
        
        // If field is emptied, clear selectedApp
        if (!appName) {
            selectedApp = '';
            dispatch('selectedApp', { appName: '' });
        } else {
            const exactMatch = tfaApps.find(app => app.toLowerCase() === appName.toLowerCase());
            if (exactMatch) {
                handleResultClick(exactMatch);
            } else if (appName.length >= 3) {
                // Show the text content of the search input if no exact match and length is at least 3 characters
                dispatch('selectedApp', { appName });
            }
        }
    }

    function handleResultClick(result: string) {
        appName = result;
        selectedApp = result;
        showSearchResults = false;
        // Dispatch event with selected app name
        dispatch('selectedApp', { appName: result });
    }

    async function handleContinue() {
        errorMessage = ''; // Clear previous errors
        const finalAppName = appName.trim(); // Use trimmed input value

        // Basic validation (already partially handled by button visibility)
        if (finalAppName.length < 3 || finalAppName.length > 40) {
            errorMessage = "App name must be between 3 and 40 characters.";
            return;
        }

        try {
            isLoading = true; // Show loading indicator potentially
            const result = await authStore.setup2FAProvider(finalAppName);
            
            if (result.success) {
                // Skip steps 7 and 8 - go directly to step 9
                dispatch('step', { step: 9 });
            } else {
                // Show error message from API using InputWarning
                errorMessage = result.message || "Failed to save app name. Please try again.";
            }
        } catch (error) {
            console.error("Error in handleContinue calling setup2FAProvider:", error);
            errorMessage = "An unexpected error occurred. Please try again.";
        } finally {
            isLoading = false; // Hide loading indicator
        }
    }

    function handleFocus() {
        showSearchResults = true;
    }

    function handleBlur() {
        setTimeout(() => showSearchResults = false, 200); // Delay to allow click event to register
    }
</script>

<div class="bottom-content">
    <div class="input-group">
        {#if showSearchResults}
            <div class="search-results">
                {#each searchResults as result}
                    <div
                        class="search-result"
                        role="button"
                        tabindex="0"
                        on:click={() => handleResultClick(result)}
                        on:keydown={(e) => e.key === 'Enter' && handleResultClick(result)}
                    >
                        <span class="icon provider-{tfaAppIcons[result]} mini-icon"></span>
                        <span class="app-name">{result}</span>
                    </div>
                {/each}
                {#if searchResults.length === 0}
                    <div class="safety-tip">
                        <div class="icon header_size warning"></div>
                        <div class="safety-tip-text">
                            <strong>{@html $text('signup.safety_tip.text')}</strong>
                            <div class="safety-tip-subtext">
                                {@html $text('signup.separate_2fa_app.text')}
                            </div>
                        </div>
                    </div>
                {/if}
            </div>
        {/if}
        <div class="input-wrapper">
            <span class="clickable-icon icon_search"></span>
            {#if selectedApp}
                <span class="icon provider-{tfaAppIcons[selectedApp]} mini-icon inside-input"></span>
            {/if}
            <input
                bind:this={appInput}
                type="text"
                bind:value={appName}
                class:selected-app={selectedApp}
                on:input={handleInput}
                on:focus={handleFocus}
                on:blur={handleBlur}
                placeholder={$text('signup.click_to_enter_app_name.text')}
                maxlength="40"
            />
        </div>
    </div>
    {#if errorMessage}
        <InputWarning message={errorMessage} target={continueButtonElement} />
    {/if}
    {#if showContinueButton}
        <button bind:this={continueButtonElement} class="continue-button" on:click={handleContinue} disabled={isLoading}>
            {@html $text('signup.continue.text')}
        </button>
    {:else if isLoading && !errorMessage}
         <button bind:this={continueButtonElement} class="continue-button" disabled>
            {@html $text('login.loading.text')}
        </button>
    {/if}
</div>

<style>
    .bottom-content {
        padding: 24px;
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .input-group {
        position: relative;
        margin-bottom: 5px;
    }

    .input-wrapper {
        display: flex;
        align-items: center;
        position: relative;
    }

    .clickable-icon {
        margin-right: 8px;
    }

    .search-results {
        width: 90%;
        position: absolute;
        bottom: calc(100% + 10px);
        left: 5%;
        right: 5%;
        background: var(--color-grey-0);
        border: 1px solid var(--color-grey-20);
        z-index: 10;
        max-height: 300px;
        height: auto;
        overflow: hidden;
        border-radius: 15px;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        transition: opacity 0.3s ease-in-out;
        opacity: 0;
        animation: fadeIn 0.3s forwards;
    }

    .search-results.hidden {
        animation: fadeOut 0.3s forwards;
    }

    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }

    @keyframes fadeOut {
        from { opacity: 1; }
        to { opacity: 0; }
    }

    .search-result {
        padding: 5px 10px;
        cursor: pointer;
        display: flex;
        align-items: center;
        text-align: left;
        transition: all 0.2s;
        border-radius: 15px;
    }

    .search-result:first-child {
        padding-top: 10px;
    }

    .search-result:last-child {
        padding-bottom: 10px;
        margin-bottom: 0;
    }

    .search-result:hover {
        background: var(--color-grey-10);
    }

    .mini-icon {
        width: 44px;
        height: 44px;
        border-radius: 8px;
        margin-right: 11px;
        opacity: 1;
        animation: unset;
        animation-delay: unset;
    }

    .inside-input {
        position: absolute;
        left: 50px;
        top: 50%;
        transform: translateY(-50%);
        width: 38px;
        height: 38px;
    }

    input {
        padding-left: 10px; /* Default padding */
    }

    input.selected-app {
        padding-left: 100px; /* Increase padding to avoid text being hidden behind the icon */
    }

    .continue-button {
        align-self: center;
        width: 90%;
    }

    .safety-tip {
        padding: 30px;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        gap: 7px;
    }

    .safety-tip-text {
        font-weight: bold;
    }

    .safety-tip-subtext {
        margin-top: 20px;
    }
</style>
