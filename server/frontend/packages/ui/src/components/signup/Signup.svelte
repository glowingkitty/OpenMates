<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { getWebsiteUrl } from '../../config/links';
    import { _ } from 'svelte-i18n';
    import { tooltip } from '../../actions/tooltip';
    import Step1EnterBasics from './steps/Step1EnterBasics.svelte';
    import SignupNav from './SignupNav.svelte';
    import { fade } from 'svelte/transition';
    
    const dispatch = createEventDispatcher();

    function handleSwitchToLogin() {
        dispatch('switchToLogin');
    }

    function handleSkip() {
        // Handle skip action
    }
</script>

<div class="signup-content" in:fade={{ duration: 400 }}>
    <SignupNav 
        on:back={handleSwitchToLogin}
        on:skip={handleSkip}
        showSkip={false}
    />
    <Step1EnterBasics on:switchToLogin={handleSwitchToLogin} />
    <a href={getWebsiteUrl('/docs')} target="_blank" use:tooltip rel="noopener noreferrer" class="help-button-container" aria-label={$_('documentation.open_documentation.text')}>
        <div class="help-button"></div>
    </a>
</div>