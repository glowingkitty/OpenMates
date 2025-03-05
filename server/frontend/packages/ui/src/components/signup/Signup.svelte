<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { _ } from 'svelte-i18n';
    import { tooltip } from '../../actions/tooltip';
    import Step1EnterBasics from './steps/Step1EnterBasics.svelte';
    import SignupNav from './SignupNav.svelte';
    import { fade, fly } from 'svelte/transition';
    import { cubicInOut } from 'svelte/easing';
    import ExpandableHeader from './ExpandableHeader.svelte';

    // Import signup state stores
    import { isSignupSettingsStep, isInSignupProcess, isSettingsStep } from '../../stores/signupState';
    import { settingsMenuVisible } from '../Settings.svelte';

    // Dynamic imports for step contents
    import Step2TopContent from './steps/step2/Step2TopContent.svelte';
    import Step3TopContent from './steps/step3/Step3TopContent.svelte';
    import Step4TopContent from './steps/step4/Step4TopContent.svelte';
    import Step5TopContent from './steps/step5/Step5TopContent.svelte';
    import Step6TopContent from './steps/step6/Step6TopContent.svelte';
    import Step7TopContent from './steps/step7/Step7TopContent.svelte';
    import Step8TopContent from './steps/step8/Step8TopContent.svelte';
    import Step9TopContent from './steps/step9/Step9TopContent.svelte';
    import Step10TopContent from './steps/step10/Step10TopContent.svelte';
    import Step2BottomContent from './steps/step2/Step2BottomContent.svelte';
    import Step3BottomContent from './steps/step3/Step3BottomContent.svelte';
    import Step4BottomContent from './steps/step4/Step4BottomContent.svelte';
    import Step5BottomContent from './steps/step5/Step5BottomContent.svelte';
    import Step6BottomContent from './steps/step6/Step6BottomContent.svelte';
    import Step7BottomContent from './steps/step7/Step7BottomContent.svelte';
    import Step8BottomContent from './steps/step8/Step8BottomContent.svelte';
    import Step9BottomContent from './steps/step9/Step9BottomContent.svelte';
    import Step10BottomContent from './steps/step10/Step10BottomContent.svelte';

    import SignupStatusbar from './SignupStatusbar.svelte';

    const dispatch = createEventDispatcher();

    let currentStep = 1;
    let direction: 'forward' | 'backward' = 'forward';
    let isInviteCodeValidated = false;
    let previousStep = 1;

    // Lift form state up
    let username = '';
    let email = '';
    let selectedAppName: string | null = null;
    let selectedCreditsAmount: number = 21000; // Default credits amount
    let selectedPrice: number = 20; // Default price
    let selectedCurrency: string = 'EUR'; // Default currency
    let limitedRefundConsent = false;

    // Animation parameters
    const flyParams = {
        duration: 400,
        x: 100,
        easing: cubicInOut
    };

    let isImageProcessing = false;
    let isImageUploading = false;

    // State to track if payment form is showing (after consent is given)
    let paymentFormVisible = false;
    let refundConsentGiven = false;

    // Track both consent and the current visible screen
    let paymentConsentGiven = false;      // Has consent been given?
    let showingPaymentForm = false;       // Is payment form currently visible?

    // New state to track payment processing status
    let paymentState = 'idle';
    
    // Create derived state for showing/hiding nav and status bar
    $: showUIControls = paymentState !== 'processing' && paymentState !== 'success';
    
    // Fade transition parameters - make them slower for better visibility
    const fadeParams = {
        duration: 600
    };

    // Update stores when component is mounted and destroyed
    import { onMount, onDestroy } from 'svelte';
    
    onMount(() => {
        isInSignupProcess.set(true);
        updateSettingsStep();
    });
    
    onDestroy(() => {
        isInSignupProcess.set(false);
        isSignupSettingsStep.set(false);
    });

    // Improved function to update settings step state based on current step
    function updateSettingsStep() {
        // Check if current step should show settings (step 7 and higher)
        const shouldShowSettings = isSettingsStep(currentStep);
        isSignupSettingsStep.set(shouldShowSettings);
        
        // If transitioning between settings/non-settings steps
        const wasShowingSettings = isSettingsStep(previousStep);
        
        if (!wasShowingSettings && shouldShowSettings) {
            // First entry into a settings step - don't auto-open menu
            // Just update the state to indicate we're in settings mode
        } else if (wasShowingSettings && !shouldShowSettings) {
            // Leaving settings steps - close menu
            settingsMenuVisible.set(false);
        } else if (wasShowingSettings && shouldShowSettings) {
            // Transitioning between settings steps - preserve menu state
            // Don't change settingsMenuVisible here
        }
    }

    // Make sure to call updateSettingsStep when the step changes
    $: if (currentStep !== previousStep) {
        previousStep = currentStep;
        updateSettingsStep();
    }

    function handleSwitchToLogin() {
        dispatch('switchToLogin');
    }

    function handleSkip() {
        if (currentStep === 3) {
            goToStep(4);
        } else if (currentStep === 6) {
            // Only skip if no app is selected
            goToStep(7);
        }
    }

    function handleStep(event: CustomEvent<{step: number, credits_amount?: number, price?: number, currency?: string}>) {
        const newStep = event.detail.step;
        direction = newStep > currentStep ? 'forward' : 'backward';
        previousStep = currentStep;
        currentStep = newStep;
        
        // If credits amount is provided (from step 9 to 10), store it
        if (event.detail.credits_amount !== undefined) {
            selectedCreditsAmount = event.detail.credits_amount;
        }

        // Store price and currency if provided
        if (event.detail.price !== undefined) {
            selectedPrice = event.detail.price;
        }

        if (event.detail.currency !== undefined) {
            selectedCurrency = event.detail.currency;
        }
        
        // updateSettingsStep() is called via the reactive statement
    }

    function handleSelectedApp(event: CustomEvent<{ appName: string }>) {
        selectedAppName = event.detail.appName;
    }

    function goToStep(step: number) {
        direction = step > currentStep ? 'forward' : 'backward';
        previousStep = currentStep;
        currentStep = step;
        // updateSettingsStep() is called via the reactive statement
    }

    function handleLogout() {
        // Handle logout and switch to login
        dispatch('switchToLogin');
    }

    function handleImageUploading(event: CustomEvent<{isProcessing: boolean, isUploading: boolean}>) {
        isImageProcessing = event.detail.isProcessing;
        isImageUploading = event.detail.isUploading;
    }

    // Handle limited refund consent from Step10TopContent
    function handleRefundConsent(event: CustomEvent<{consented: boolean}>) {
        limitedRefundConsent = event.detail.consented;
        paymentConsentGiven = event.detail.consented;
    }
    
    // Track when payment form becomes visible or hidden
    function handlePaymentFormVisibilityChange(event: CustomEvent<{visible: boolean}>) {
        showingPaymentForm = event.detail.visible;
    }
    
    // Handle open refund info request
    function handleOpenRefundInfo() {
        window.open(getWebsiteUrl(routes.docs.userGuide_signup_10_1), '_blank');
    }
    
    // Handle payment submission
    function handlePaymentSubmission(event: CustomEvent<{
        nameOnCard: string,
        cardNumber: string,
        expireDate: string,
        cvv: string,
        amount: number
    }>) {
        console.log('Processing payment...', event.detail);
        // Implement payment submission logic here
        
        // For demo, simulate success and move to next step
        goToStep(11);  // Move to completion step
    }

    // Handle payment state changes
    function handlePaymentStateChange(event) {
        paymentState = event.detail.state;
        
        // If payment failed, reset to idle state after a short delay
        if (paymentState === 'failure') {
            setTimeout(() => {
                paymentState = 'idle';
            }, 500);
        }
    }

    // Get the appropriate help documentation link based on current step and validation state
    $: helpLink = getWebsiteUrl(
        currentStep === 1 
            ? (!isInviteCodeValidated ? routes.docs.userGuide_signup_1a : routes.docs.userGuide_signup_1b)
            : currentStep === 10
                ? (showingPaymentForm ? routes.docs.userGuide_signup_10_2 : routes.docs.userGuide_signup_10_1)
                : routes.docs[`userGuide_signup_${currentStep}`]
    );

    // Update showSkip logic to show for steps 3 and 6
    $: showSkip = currentStep === 3 || currentStep === 6;

    // Show expanded header on step 9 and 10
    $: showExpandedHeader = currentStep === 9 || currentStep === 10;

    // For step 10, use expanded height for the top content wrapper
    $: isExpandedTopContent = currentStep === 10;
</script>

<div class="signup-content visible" in:fade={{ duration: 400 }}>
    {#if showUIControls}
        <div transition:fade={fadeParams}>
            <SignupNav 
                on:back={handleSwitchToLogin}
                on:step={handleStep}
                on:skip={handleSkip}
                on:logout={handleLogout}
                {showSkip}
                {currentStep}
                {selectedAppName}
            />
        </div>
    {/if}

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
                <div class="top-content-wrapper" class:expanded={isExpandedTopContent}>
                    <div class="top-content">
                        <ExpandableHeader 
                            visible={showExpandedHeader} 
                            credits_amount={currentStep === 10 ? selectedCreditsAmount : undefined}
                        />
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
                                    {:else if currentStep === 10}
                                        <Step10TopContent 
                                            credits_amount={selectedCreditsAmount} 
                                            price={selectedPrice} 
                                            currency={selectedCurrency}
                                            on:consentGiven={handleRefundConsent}
                                            on:paymentFormVisibility={handlePaymentFormVisibilityChange}
                                            on:openRefundInfo={handleOpenRefundInfo}
                                            on:payment={handlePaymentSubmission}
                                            on:paymentStateChange={handlePaymentStateChange}
                                        />
                                    {/if}
                                </div>
                            {/key}
                        </div>
                    </div>
                </div>

                <!-- Bottom content wrapper -->
                <div class="bottom-content-wrapper" class:reduced={isExpandedTopContent}>
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
                                            currentStep === 10 ? Step10BottomContent :
                                           null}
                                    on:step={handleStep}
                                    on:uploading={handleImageUploading}
                                    on:selectedApp={handleSelectedApp}
                                    {selectedAppName}
                                />
                            </div>
                        {/key}
                    </div>
                </div>
            </div>
        {/if}
    </div>

    {#if showUIControls}
        <div class="status-wrapper" class:hidden={currentStep === 1} transition:fade={fadeParams}>
            <SignupStatusbar {currentStep} />
        </div>
    {/if}

    {#if showUIControls}
        <div class="help-wrapper" transition:fade={fadeParams}>
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
    {:else}
        <div class="help-wrapper hidden"></div>
    {/if}
</div>

<style>
    /* Add these styles to your existing CSS */
    .top-content-wrapper {
        transition: height 0.6s cubic-bezier(0.22, 1, 0.36, 1);
    }
    
    .top-content-wrapper.expanded {
        height: 640px;
    }
    
    /* Add a class for hiding elements with transition */
    .hidden {
        opacity: 0;
        visibility: hidden;
        transition: opacity 0.6s ease, visibility 0.6s ease;
    }
</style>