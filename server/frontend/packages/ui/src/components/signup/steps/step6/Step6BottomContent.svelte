<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
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
    import { text } from '@repo/ui';
    import { onMount } from 'svelte';
    import { createEventDispatcher } from 'svelte';
    import { tfaApps, tfaAppIcons } from '../../../../config/tfa';

    let appName = '';
    let appInput: HTMLInputElement;
    const dispatch = createEventDispatcher();
    let showSearchResults = false;
    let searchResults = tfaApps;
    let selectedApp = '';

    function handleInput(event: Event) {
        const input = event.target as HTMLInputElement;
        appName = input.value;
        showSearchResults = true;
        searchResults = appName ? tfaApps.filter(app => app.toLowerCase().includes(appName.toLowerCase())) : tfaApps;
        selectedApp = '';
    }

    function handleResultClick(result: string) {
        appName = result;
        selectedApp = result;
        showSearchResults = false;
    }

    function handleContinue() {
        if (appName || selectedApp) {
            dispatch('step', { step: 7 });
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
                    <div class="search-result">
                        {@html $text('signup.safety_tip.text')}
                        <br />
                        {@html $text('signup.separate_2fa_app.text')}
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
                on:input={handleInput}
                on:focus={handleFocus}
                on:blur={handleBlur}
                placeholder={$text('signup.click_to_enter_app_name.text')}
            />
        </div>
    </div>
    {#if appName.length >= 3 || selectedApp}
        <button class="continue-button" on:click={handleContinue}>
            {@html $text('signup.continue.text')}
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
    }

    .input-wrapper {
        display: flex;
        align-items: center;
        position: relative;
    }

    .clickable-icon {
        margin-right: 8px;
    }

    .inside-input {
        position: absolute;
        left: 8px;
        top: 50%;
        transform: translateY(-50%);
    }

    .search-results {
        position: absolute;
        bottom: 100%;
        left: 0;
        right: 0;
        background: var(--color-grey-0);
        border: 1px solid #ccc;
        z-index: 10;
        max-height: 200px;
        overflow-y: auto;
        border-radius: 15px;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        overflow-x: hidden;
    }

    .search-result {
        padding: 8px;
        cursor: pointer;
        display: flex;
        align-items: center;
        width: 100%;
        text-align: left;
        transition: all 0.2s;
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

    .continue-button {
        align-self: flex-end;
    }
</style>
