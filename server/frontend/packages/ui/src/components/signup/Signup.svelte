<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { _ } from 'svelte-i18n';
    import { tooltip } from '../../actions/tooltip';
    import Step1EnterBasics from './steps/Step1EnterBasics.svelte';
    import SignupNav from './SignupNav.svelte';
    import { fade, fly } from 'svelte/transition';
    import { cubicInOut } from 'svelte/easing';

    // Dynamic imports for step contents
    import Step2TopContent from './steps/step2/Step2TopContent.svelte';
    import Step2BottomContent from './steps/step2/Step2BottomContent.svelte';
    import Step3TopContent from './steps/step3/Step3TopContent.svelte';
    import Step3BottomContent from './steps/step3/Step3BottomContent.svelte';
    // ... import other step contents
    
    const dispatch = createEventDispatcher();

    let currentStep = 1;
    let direction: 'forward' | 'backward' = 'forward';
    let isInviteCodeValidated = false;

    // Lift form state up
    let username = '';
    let email = '';

    // Animation parameters
    const flyParams = {
        duration: 400,
        x: 100,
        easing: cubicInOut
    };

    function handleSwitchToLogin() {
        dispatch('switchToLogin');
    }

    function handleSkip() {
        // Handle skip action
    }

    function handleStep(event: CustomEvent<{step: number}>) {
        const newStep = event.detail.step;
        direction = newStep > currentStep ? 'forward' : 'backward';
        currentStep = newStep;
    }

    function goToStep(step: number) {
        direction = step > currentStep ? 'forward' : 'backward';
        currentStep = step;
    }

    // Get the appropriate help documentation link based on current step
    $: helpLink = getWebsiteUrl(routes.docs[`userGuide_signup_${currentStep}`]);
</script>

<div class="signup-content" in:fade={{ duration: 400 }}>
    <SignupNav 
        on:back={handleSwitchToLogin}
        on:step={handleStep}
        on:skip={handleSkip}
        showSkip={false}
        {currentStep}
    />

    {#if currentStep === 1}
        <Step1EnterBasics 
            on:switchToLogin={handleSwitchToLogin}
            bind:isValidated={isInviteCodeValidated}
            bind:username
            bind:email
            on:next={() => goToStep(2)}
        />
    {:else}
        <div class="step-layout">
            <!-- Persistent top content block -->
            <div class="top-content-wrapper">
                <div class="top-content">
                    {#key currentStep}
                        <div 
                            in:fly={{...flyParams, x: direction === 'forward' ? 100 : -100}}
                            out:fly={{...flyParams, x: direction === 'forward' ? -100 : 100}}
                        >
                            {#if currentStep === 2}
                                <Step2TopContent email={email || ''} />
                            {:else if currentStep === 3}
                                <Step3TopContent />
                            {/if}
                        </div>
                    {/key}
                </div>
            </div>

            <!-- Persistent bottom content block -->
            <div class="bottom-content-wrapper">
                {#key currentStep}
                    <div 
                        in:fly={{...flyParams, x: direction === 'forward' ? 100 : -100}}
                        out:fly={{...flyParams, x: direction === 'forward' ? -100 : 100}}
                    >
                        <svelte:component 
                            this={currentStep === 2 ? Step2BottomContent :
                                  currentStep === 3 ? Step3BottomContent : null}
                        />
                    </div>
                {/key}
            </div>
        </div>
    {/if}

    <a href={helpLink} 
       target="_blank" 
       use:tooltip 
       rel="noopener noreferrer" 
       class="help-button-container" 
       aria-label={$_('documentation.open_documentation.text')}
    >
        <div class="help-button"></div>
    </a>
</div>