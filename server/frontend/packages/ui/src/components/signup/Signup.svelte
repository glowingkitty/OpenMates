<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { getWebsiteUrl } from '../../config/links';
    import { _ } from 'svelte-i18n';
    import { tooltip } from '../../actions/tooltip';
    import Step1EnterBasics from './Step1EnterBasics.svelte';
    
    const dispatch = createEventDispatcher();

    function handleSwitchToLogin() {
        dispatch('switchToLogin');
    }
</script>

<div class="signup-content">
    <Step1EnterBasics on:switchToLogin={handleSwitchToLogin} />
    <a href={getWebsiteUrl('/docs')} target="_blank" use:tooltip rel="noopener noreferrer" class="help-button-container" aria-label={$_('documentation.open_documentation.text')}>
        <div class="help-button"></div>
    </a>
</div>