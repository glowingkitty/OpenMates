<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import Step1EnterBasics from './Step1EnterBasics.svelte';
    
    const dispatch = createEventDispatcher();

    function handleSwitchToLogin() {
        dispatch('switchToLogin');
    }
</script>

<div class="signup-content">
    <Step1EnterBasics on:switchToLogin={handleSwitchToLogin} />
</div>
