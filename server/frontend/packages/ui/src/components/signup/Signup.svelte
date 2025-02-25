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
    import Step3TopContent from './steps/step3/Step3TopContent.svelte';
    import Step4TopContent from './steps/step4/Step4TopContent.svelte';
    import Step5TopContent from './steps/step5/Step5TopContent.svelte';
    import Step6TopContent from './steps/step6/Step6TopContent.svelte';
    import Step7TopContent from './steps/step7/Step7TopContent.svelte';
    import Step8TopContent from './steps/step8/Step8TopContent.svelte';
    import Step9TopContent from './steps/step9/Step9TopContent.svelte';
    import Step2BottomContent from './steps/step2/Step2BottomContent.svelte';
    import Step3BottomContent from './steps/step3/Step3BottomContent.svelte';
    import Step4BottomContent from './steps/step4/Step4BottomContent.svelte';
    import Step5BottomContent from './steps/step5/Step5BottomContent.svelte';
    import Step6BottomContent from './steps/step6/Step6BottomContent.svelte';
    import Step7BottomContent from './steps/step7/Step7BottomContent.svelte';
    import Step8BottomContent from './steps/step8/Step8BottomContent.svelte';
    import Step9BottomContent from './steps/step9/Step9BottomContent.svelte';
    
    import SignupStatusbar from './SignupStatusbar.svelte';

    const dispatch = createEventDispatcher();

    let currentStep = 1;
    let direction: 'forward' | 'backward' = 'forward';
    let isInviteCodeValidated = false;

    // Lift form state up
    let username = '';
    let email = '';
    let selectedAppName: string | null = null;

    // Animation parameters
    const flyParams = {
        duration: 400,
        x: 100,
        easing: cubicInOut
    };

    let isImageProcessing = false;
    let isImageUploading = false;

    function handleSwitchToLogin() {
        dispatch('switchToLogin');
    }

    function handleSkip() {
        if (currentStep === 3) {
            goToStep(4);
        }
    }

    function handleStep(event: CustomEvent<{step: number}>) {
        const newStep = event.detail.step;
        direction = newStep > currentStep ? 'forward' : 'backward';
        currentStep = newStep;
    }

    function handleSelectedApp(event: CustomEvent<{ appName: string }>) {
        selectedAppName = event.detail.appName;
    }

    function goToStep(step: number) {
        direction = step > currentStep ? 'forward' : 'backward';
        currentStep = step;
    }

    function handleLogout() {
        // Handle logout and switch to login
        dispatch('switchToLogin');
    }

    function handleImageUploading(event: CustomEvent<{isProcessing: boolean, isUploading: boolean}>) {
        isImageProcessing = event.detail.isProcessing;
        isImageUploading = event.detail.isUploading;
    }

    // Get the appropriate help documentation link based on current step and validation state
    $: helpLink = getWebsiteUrl(
        currentStep === 1 
            ? (!isInviteCodeValidated ? routes.docs.userGuide_signup_1a : routes.docs.userGuide_signup_1b)
            : routes.docs[`userGuide_signup_${currentStep}`]
    );

    // Update showSkip logic to only show for step 3
    $: showSkip = currentStep === 3;
</script>

<div class="signup-content visible" in:fade={{ duration: 400 }}>
    <SignupNav 
        on:back={handleSwitchToLogin}
        on:step={handleStep}
        on:skip={handleSkip}
        on:logout={handleLogout}
        {showSkip}
        {currentStep}
    />

    <div>
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
                <!-- Top content wrapper -->
                <div class="top-content-wrapper">
                    <div class="top-content">
                        <div class="content-slider">
                            {#key currentStep}
                                <div 
                                    class="slide"
                                    in:fly={{...flyParams, x: direction === 'forward' ? 100 : -100}}
                                    out:fly={{...flyParams, x: direction === 'forward' ? -100 : 100}}
                                >
                                    {#if currentStep === 2}
                                        <Step2TopContent {email} />
                                    {:else if currentStep === 3}
                                        <Step3TopContent 
                                            {username} 
                                            isProcessing={isImageProcessing}
                                            isUploading={isImageUploading}
                                        />
                                    {:else if currentStep === 4}
                                        <Step4TopContent />
                                    {:else if currentStep === 5}
                                        <Step5TopContent />
                                    {:else if currentStep === 6}
                                        <Step6TopContent {selectedAppName} />
                                    {:else if currentStep === 7}
                                        <Step7TopContent />
                                    {:else if currentStep === 8}
                                        <Step8TopContent />
                                    {:else if currentStep === 9}
                                        <Step9TopContent />
                                    {/if}
                                </div>
                            {/key}
                        </div>
                    </div>
                </div>

                <!-- Bottom content wrapper -->
                <div class="bottom-content-wrapper">
                    <div class="content-slider">
                        {#key currentStep}
                            <div 
                                class="slide"
                                in:fly={{...flyParams, x: direction === 'forward' ? 100 : -100}}
                                out:fly={{...flyParams, x: direction === 'forward' ? -100 : 100}}
                            >
                                <svelte:component 
                                    this={
                                            currentStep === 2 ? Step2BottomContent :
                                            currentStep === 3 ? Step3BottomContent :
                                            currentStep === 4 ? Step4BottomContent :
                                            currentStep === 5 ? Step5BottomContent :
                                            currentStep === 6 ? Step6BottomContent :
                                            currentStep === 7 ? Step7BottomContent :
                                            currentStep === 8 ? Step8BottomContent :
                                            currentStep === 9 ? Step9BottomContent :
                                           null}
                                    on:step={handleStep}
                                    on:uploading={handleImageUploading}
                                    on:selectedApp={handleSelectedApp}
                                />
                            </div>
                        {/key}
                    </div>
                </div>
            </div>
        {/if}
    </div>

    <div class="status-wrapper" class:hidden={currentStep === 1}>
        <SignupStatusbar {currentStep} />
    </div>

    <div class="help-wrapper" class:hidden={currentStep === 1}>
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
</div>