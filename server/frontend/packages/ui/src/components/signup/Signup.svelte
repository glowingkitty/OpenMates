<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { _ } from 'svelte-i18n';
    import { tooltip } from '../../actions/tooltip';
    import Step1EnterBasics from './steps/Step1EnterBasics.svelte';
    import SignupNav from './SignupNav.svelte';
    import { fade } from 'svelte/transition';
    
    const dispatch = createEventDispatcher();

    // Track if invite code is validated
    let isInviteCodeValidated = false;

    function handleSwitchToLogin() {
        dispatch('switchToLogin');
    }

    function handleSkip() {
        // Handle skip action
    }

    // Get the appropriate help documentation link
    $: helpLink = getWebsiteUrl(
        isInviteCodeValidated 
            ? routes.docs.userGuide_signup_basics 
            : routes.docs.userGuide_signup_invitecode
    );
</script>

<div class="signup-content" in:fade={{ duration: 400 }}>
    <SignupNav 
        on:back={handleSwitchToLogin}
        on:skip={handleSkip}
        showSkip={false}
    />
    <Step1EnterBasics 
        on:switchToLogin={handleSwitchToLogin}
        bind:isValidated={isInviteCodeValidated}
    />
    <a href={helpLink} target="_blank" use:tooltip rel="noopener noreferrer" class="help-button-container" aria-label={$_('documentation.open_documentation.text')}>
        <div class="help-button"></div>
    </a>
</div>