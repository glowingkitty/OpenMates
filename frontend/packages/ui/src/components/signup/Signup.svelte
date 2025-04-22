<script lang="ts">
    import { createEventDispatcher, tick } from 'svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { _ } from 'svelte-i18n';
    import { tooltip } from '../../actions/tooltip';
    import Step1EnterBasics from './steps/Step1EnterBasics.svelte';
    import SignupNav from './SignupNav.svelte';
    import { fade, fly } from 'svelte/transition';
    import { cubicInOut } from 'svelte/easing';
    import ExpandableHeader from './ExpandableHeader.svelte';
    import { MOBILE_BREAKPOINT } from '../../styles/constants';
    import { isMenuOpen } from '../../stores/menuState';
    
    // Import signup state stores
    import { isSignupSettingsStep, isInSignupProcess, isSettingsStep, currentSignupStep, showSignupFooter } from '../../stores/signupState';
    import { authStore, isCheckingAuth } from '../../stores/authStore';
    import { isLoggingOut } from '../../stores/signupState';
    import { updateProfile } from '../../stores/userProfile';
    import { panelState } from '../../stores/panelStateStore'; // Added panelState import

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

    // Initialize step from store instead of always starting at 1
    let currentStep = 1;
    let direction: 'forward' | 'backward' = 'forward';
    let isInviteCodeValidated = false;
    let is_admin = false; // Add this to track admin status
    // let previousStep = 1; // Removed, will pass previous value directly

    // Lift form state up
    let username = '';
    let email = '';
    let selectedAppName: string | null = null;
    let selectedCreditsAmount: number = 21000; // Default credits amount
    let selectedPrice: number = 20; // Default price
    let selectedCurrency: string = 'EUR'; // Default currency
    let isGiftFlow: boolean = false; // Track if it's a gift flow
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
        
        // Check if we're starting a fresh signup from the login screen
        // If we are, make sure we're at step 1
        if (!$authStore.isAuthenticated) {
            currentSignupStep.set(1);
            currentStep = 1;
        } else {
            // Otherwise, get step from store if set (for authenticated users continuing signup)
            currentStep = $currentSignupStep;
        }
        
        updateSettingsStep(0); // Provide 0 as initial prevStepValue
        showSignupFooter.set(currentStep < 7); // Set initial footer state
    });
    
    onDestroy(() => {
        isInSignupProcess.set(false);
        isSignupSettingsStep.set(false);
        showSignupFooter.set(true); // Reset footer state on destroy
    });

    // Function to update settings step state and close panel if necessary
    function updateSettingsStep(prevStepValue: number) {
        // Check if current step should show settings (step 7 and higher)
        const shouldShowSettings = isSettingsStep(currentStep);
        isSignupSettingsStep.set(shouldShowSettings);

        // Check if the previous step was a settings step
        const wasShowingSettings = isSettingsStep(prevStepValue);

        // If leaving settings steps, close the menu using panelState
        if (wasShowingSettings && !shouldShowSettings) {
            panelState.closeSettings();
        }
        // No need to handle opening or preserving state here,
        // as panelStateStore manages the global state.
    }

    // Removed reactive block for previousStep handling

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

    async function handleStep(event: CustomEvent<{step: number, credits_amount?: number, price?: number, currency?: string, isGift?: boolean}>) { // Add isGift to type
        const newStep = event.detail.step;
        const oldStep = currentStep; // Capture old step value
        direction = newStep > oldStep ? 'forward' : 'backward';
        isGiftFlow = event.detail.isGift ?? false; // Capture isGift status, default to false
        currentStep = newStep; // Update local step
        currentSignupStep.set(newStep); // Update the global store
        await tick(); // Wait for Svelte to process state changes before proceeding
        updateSettingsStep(oldStep); // Call update function with old step value
        showSignupFooter.set(newStep < 7); // Update footer state

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

    async function goToStep(step: number) {
        const oldStep = currentStep; // Capture old step value
        direction = step > oldStep ? 'forward' : 'backward';
        currentStep = step;
        currentSignupStep.set(step); // Also update the store here
        await tick(); // Add tick here too for consistency
        updateSettingsStep(oldStep); // Call update function with old step value
        showSignupFooter.set(step < 7); // Update footer state
    }

    async function handleLogout() {
        try {
            isLoggingOut.set(true);
            isInSignupProcess.set(false);
            
            // Reset signup step to 1 when logging out
            currentSignupStep.set(1);

            await authStore.logout({
                beforeServerLogout: () => {
                    isCheckingAuth.set(false);
                },

                afterServerLogout: async () => {
                    // Longer delay to ensure UI transitions complete correctly
                    await new Promise(resolve => setTimeout(resolve, 500));
                }
            });
            
            // Keep the logging out state for a moment longer to prevent UI flash
            setTimeout(() => {
                isLoggingOut.set(false);
            }, 300);
            
            // Switch to login view after logout is complete
            showSignupFooter.set(true); // Ensure footer is shown after logout
            dispatch('switchToLogin');
        } catch (error) {
            console.error('Error during logout:', error);
            showSignupFooter.set(true); // Ensure footer is shown even on error
            // Even on error, ensure we exit signup mode properly
            isInSignupProcess.set(false);
            
            // Reset signup step to 1 when logging out
            currentSignupStep.set(1);
            
            authStore.logout();
            
            // Reset logging out state
            setTimeout(() => {
                isLoggingOut.set(false);
            }, 300);
            
            dispatch('switchToLogin');
        }
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
        console.debug('Processing payment...', event.detail);
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
        } else if (paymentState === 'success') { // Add success handling
            console.debug("Payment successful, transitioning to chat in 2 seconds...");
            // Introduce a 2-second delay before transitioning
            setTimeout(() => {
                // Update last_opened to signal completion of signup flow
                updateProfile({ last_opened: '/chat/new' });
                // Signal completion of signup process
                isInSignupProcess.set(false);
                if (window.innerWidth >= MOBILE_BREAKPOINT) {
                    isMenuOpen.set(true);
                }
                // The reactive statements in +page.svelte and ActiveChat.svelte
                // should handle the transition to the chat view when isInSignupProcess is false
                console.debug("Transitioning to chat now.");
            }, 2000); // 2000 milliseconds = 2 seconds
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

    // Update showSkip logic to show for steps 3, 6, and 9
    $: showSkip = currentStep === 3 || currentStep === 6 || currentStep === 9;

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
                showAdminButton={is_admin && currentStep === 1 && isInviteCodeValidated}
            />
        </div>
    {/if}

    <div>
        {#if currentStep === 1}
            <Step1EnterBasics 
                on:switchToLogin={handleSwitchToLogin}
                bind:isValidated={isInviteCodeValidated}
                bind:is_admin={is_admin}
                bind:username
                bind:email
                on:next={() => goToStep(2)}
                on:requestSwitchToLogin={handleSwitchToLogin}
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
                                            isGift={isGiftFlow}
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