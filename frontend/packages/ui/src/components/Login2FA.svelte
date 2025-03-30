<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
login_2fa_svelte:
    check_your_2fa_app_text:
        type: 'text'
        text: $text('login.check_your_2fa_app.text')
        purpose: 'Ask user to check their 2FA app for the one time code'
        bigger_context:
            - 'Login'
        tags:
            - 'login'
            - '2fa'
        connected_documentation:
            - '/login/2fa'
    tfa_app_name_text:
        type: 'text'
        text: {name of 2FA app which user used}
        purpose: 'Reminder for user which 2FA app they used, if they saved the name during signup or in settings.'
        processing:
            - 'Name of 2FA app is loaded from server (if user saved it during signup or in settings)'
            - 'Name of 2FA app is shown to user'
        bigger_context:
            - 'Login'
        tags:
            - 'login'
            - '2fa'
        connected_documentation:
            - '/login/2fa'
    enter_2fa_code_input_field:
        type: 'input_field'
        placeholder: $text('signup.enter_one_time_code.text')
        purpose:
            - 'Verifies the 2FA code, to login to the user account.'
        processing:
            - 'User clicks field (or, if on desktop, field is focused automatically)'
            - 'User enters numeric code shown in 2FA OTP app'
        bigger_context:
            - 'Login'
        tags:
            - 'login'
            - '2fa'
        connected_documentation:
            - '/login/2fa'
    login_button:
        type: 'button'
        text: $text('login.login.text')
        purpose:
            - 'User clicks to login to the user account.'
        processing:
            - 'User clicks the button'
            - 'Server request is sent to validate 2FA code'
            - 'If 2FA code valid: user is logged in'
            - 'If 2FA code not valid: informs user via error message'
        bigger_context:
            - 'Login'
        tags:
            - 'login'
            - '2fa'
        connected_documentation:
            - '/login/2fa'
    enter_backup_code_button:
        type: 'button'
        text: $text('login.enter_backup_code.text')
        purpose:
            - 'Switches to interface where user can enter backup code instead of 2FA code.'
        processing:
            - 'User clicks the button'
            - 'User is forwarded to the interface where they can enter backup code'
        bigger_context:
            - 'Login'
        tags:
            - 'login'
            - '2fa'
        connected_documentation:
            - '/login/2fa'
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount, onDestroy, createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition'; // Import fade transition
    import { tfaAppIcons } from '../config/tfa';
    import InputWarning from './common/InputWarning.svelte';

    export let previewMode = false;
    export let previewTfaAppName = 'Google Authenticator';
    export let highlight: (
        'check-2fa' |
        'app-name' | 
        'input-area' | 
        'login-btn' | 
        'enter-backup-code'
    )[] = [];

    // Add a new prop to receive the selected app name
    export let selectedAppName: string | null = null;
    // Add props for binding isLoading and displaying errors
    export let isLoading = false;
    export let errorMessage: string | null = null;
    // Add new props for backup code flow
    export let backupCodeSuccess = false;
    export let remainingBackupCodes = 0;

    const dispatch = createEventDispatcher();

    let authCode = ''; // Renamed from otpCode
    let authInput: HTMLInputElement; // Renamed from otpInput
    let isBackupMode = false; // State for backup code mode
    // Declare inputMode with the correct type
    let inputMode: 'text' | 'numeric' = 'numeric'; 
    let currentAppIndex = 0;
    let animationInterval: number | null = null;
    let currentDisplayedApp = previewMode ? previewTfaAppName : (selectedAppName || ''); // Initialize with selectedAppName

    const appNames = Object.keys(tfaAppIcons);

    // Get the icon class for the app name, or undefined if not found
    $: tfaAppIconClass = currentDisplayedApp in tfaAppIcons ? tfaAppIcons[currentDisplayedApp] : undefined;

    // Reactive statement for placeholder text
    $: inputPlaceholder = isBackupMode ? $text('login.enter_backup_code.text') : $text('signup.enter_one_time_code.text');
    // Reactive statement for button text
    $: toggleButtonText = isBackupMode ? $text('login.enter_2fa_app_code.text') : $text('login.enter_backup_code.text');
    // Reactive statement for input type (numeric for OTP, text for backup)
    $: inputMode = isBackupMode ? 'text' : 'numeric'; // Reactive assignment updates the typed variable
    $: inputMaxLength = isBackupMode ? 14 : 6; // Backup codes are longer (e.g., XXXX-XXXX-XXXX)

    // Update the animation logic to stop when a selected app is provided
    $: {
        if (selectedAppName) {
            currentDisplayedApp = selectedAppName;
            if (animationInterval) clearInterval(animationInterval);
        } else if (previewMode) {
            if (animationInterval) clearInterval(animationInterval);
            animationInterval = setInterval(() => {
                currentAppIndex = (currentAppIndex + 1) % appNames.length;
                currentDisplayedApp = appNames[currentAppIndex];
            }, 4000); // Change every 4 seconds
        } else {
            // Use selectedAppName if available, otherwise default to empty or preview
            currentDisplayedApp = selectedAppName || (previewMode ? previewTfaAppName : '');
        }
    }

    // Start animation in preview mode if no app name is selected
    onMount(() => {
        // Only start animation in preview mode AND if no specific app is selected
        if (previewMode && !selectedAppName) {
            animationInterval = setInterval(() => {
                currentAppIndex = (currentAppIndex + 1) % appNames.length;
                currentDisplayedApp = appNames[currentAppIndex];
            }, 4000); // Change every 4 seconds
        } else {
            // If not preview or an app is selected, display the correct app name
            currentDisplayedApp = selectedAppName || (previewMode ? previewTfaAppName : '');
        }
        // Focus input on mount if not preview mode and not showing success message
        if (!previewMode && authInput && !backupCodeSuccess) {
            authInput.focus();
        }
    });

    onDestroy(() => {
        if (animationInterval) clearInterval(animationInterval);
    });

    // Helper function to generate opacity style - Define allowed IDs type
    type HighlightableId = typeof highlight[number];
    $: getStyle = (id: HighlightableId) => `opacity: ${highlight.length === 0 || highlight.includes(id) ? 1 : 0.5}`;

    // Function to dispatch event to switch back to login
    function handleSwitchToLogin() {
        dispatch('switchToLogin');
    }

    // Function to toggle between OTP and Backup Code mode
    function toggleBackupMode() {
        isBackupMode = !isBackupMode;
        authCode = ''; // Clear input when switching modes
        errorMessage = null; // Clear error message
        if (authInput) {
            authInput.focus(); // Re-focus input
        }
    }

    function handleInput(event: Event) {
        const input = event.target as HTMLInputElement;
        let value = input.value;

        if (isBackupMode) {
            // Allow letters, digits, hyphens. Convert to uppercase. Limit length.
            // Basic format XXXX-XXXX-XXXX
            value = value.toUpperCase().replace(/[^A-Z0-9-]/g, '');
            // Auto-add hyphens (simple approach)
            if (value.length === 4 || value.length === 9) {
                if (!value.endsWith('-')) {
                    value += '-';
                }
            }
            // Remove trailing hyphen if user deletes back
             if (value.endsWith('-') && (value.length === 5 || value.length === 10)) {
                 // This logic might need refinement for better UX
             }
            authCode = value.slice(0, 14); // Limit to XXXX-XXXX-XXXX format length
        } else {
            // Allow only digits and limit length for OTP
            authCode = value.replace(/\D/g, '').slice(0, 6);
        }
        
        input.value = authCode; // Ensure input reflects sanitized value

        // Dispatch activity event whenever input changes
        dispatch('tfaActivity');

        // Optionally auto-submit when code reaches required length
        const requiredLength = isBackupMode ? 14 : 6;
        if (authCode.length === requiredLength) {
            handleSubmit();
        }
    }

    function handleSubmit() {
        const requiredLength = isBackupMode ? 14 : 6; // Check length based on mode
        if (isLoading || authCode.length !== requiredLength) return; // Prevent submit if loading or code incomplete
        
        // Send backup code WITH hyphens, OTP code as is
        const codeToSend = authCode; // No modification needed here

        dispatch('submitTfa', { authCode: codeToSend, codeType: isBackupMode ? 'backup' : 'otp' });
    }

    // Clear error message when user starts typing again
    $: if (authCode) {
        errorMessage = null;
    }

    // Reactive statement for currentDisplayedApp based on selectedAppName
    $: currentDisplayedApp = selectedAppName || (previewMode ? previewTfaAppName : '');

    // Function to handle the "Continue" button click after backup code success
    function handleContinue() {
        dispatch('backupLoginContinue');
    }

</script>

<div class="login-2fa {selectedAppName ? 'no-animation' : ''}" class:preview={previewMode}>
    {#if backupCodeSuccess}
        <!-- Backup Code Success View -->
        <div class="success-view" transition:fade={{ duration: 300 }}>
            <p class="success-message">
                {@html $text('login.backup_code_used_successfully.text', { 
                    values: { remaining_count: remainingBackupCodes } 
                })}
            </p>
            <button class="continue-button" on:click={handleContinue} disabled={isLoading}>
                {#if isLoading}
                    <span class="loading-spinner"></span>
                {:else}
                    {$text('signup.continue.text')}
                {/if}
            </button>
        </div>
    {:else}
        <!-- Standard 2FA / Backup Code Input View -->
        <div class="input-view" transition:fade={{ duration: 300 }}>
            <!-- Wrap check-2fa text for conditional hiding -->
            <div class="check-2fa-container" class:hidden={isBackupMode}>
                <p id="check-2fa" class="check-2fa-text" style={getStyle('check-2fa')}>
                    {@html $text('login.check_your_2fa_app.text')}
                </p>
            </div>
            
            <!-- App Name Section (conditionally hidden in backup mode) -->
            <div class="app-name-container" class:hidden={isBackupMode}>
                {#if currentDisplayedApp}
                    <p id="app-name" class="app-name" style={getStyle('app-name')}>
                        <span class="app-name-content">
                            {#if tfaAppIconClass}
                                <span class="icon provider-{tfaAppIconClass} mini-icon {previewMode && !selectedAppName ? 'fade-animation' : ''}"></span>
                            {/if}
                            <span class="{previewMode && !selectedAppName ? 'fade-text' : ''}">{currentDisplayedApp}</span>
                        </span>
                    </p>
                {/if}
            </div>

            <!-- Input Area -->
            <div id="input-area" style={getStyle('input-area')}>
                <div class="input-wrapper">
                    <span class="clickable-icon icon_2fa"></span>
                    <input
                        bind:this={authInput}
                        type="text"
                        bind:value={authCode}
                        on:input={handleInput}
                        placeholder={inputPlaceholder}
                        inputmode={inputMode}
                        maxlength={inputMaxLength}
                        autocomplete="one-time-code"
                        class:error={!!errorMessage}
                        on:keypress={(e) => { if (e.key === 'Enter') handleSubmit(); }}
                    />
                     {#if errorMessage}
                        <InputWarning 
                            message={errorMessage} 
                            target={authInput} 
                        />
                    {/if}
                </div>
            </div>
            
            <!-- Toggle Button -->
            <div id="enter-backup-code" class="enter-backup-code">
                <button on:click={toggleBackupMode} class="text-button" disabled={isLoading}>
                    {toggleButtonText}
                </button>
            </div>

            <!-- Switch Account Link -->
            <div class="switch-account">
                <a href="" on:click|preventDefault={handleSwitchToLogin} class="text-button">
                    {$text('login.login_with_another_account.text')}
                </a>
            </div>
        </div>
    {/if}
</div>

<style>
    .login-2fa {
        display: flex;
        flex-direction: column;
        min-height: 200px; /* Ensure minimum height for transitions */
    }

    .input-view, .success-view {
        display: flex;
        flex-direction: column;
        width: 100%; /* Ensure views take full width */
    }

    .check-2fa-container, /* Apply transitions to this container */
    .app-name-container {
        height: auto; /* Default height */
        opacity: 1;
        overflow: hidden;
        transition: height 0.3s ease-out, opacity 0.3s ease-out, margin 0.3s ease-out, padding 0.3s ease-out; /* Added margin/padding transition */
    }

    .check-2fa-container.hidden, /* Apply hidden styles */
    .app-name-container.hidden {
        height: 0;
        opacity: 0;
        margin: 0; /* Remove margin when hidden */
        padding: 0; /* Remove padding when hidden */
    }

    .app-name {
        display: flex;
        justify-content: center;
        width: 100%;
    }
    
    .app-name-content {
        display: flex;
        align-items: center;
    }

    .check-2fa-text {
        margin: 0px;
        color: var(--color-grey-60);
    }

    .preview {
        cursor: default !important;
    }

    .enter-backup-code {
        margin-top: 20px;
    }

    .switch-account {
        margin-top: 10px; /* Add some space above the new link */
    }

    .mini-icon {
        width: 38px;
        height: 38px;
        border-radius: 8px;
        margin-right: 10px;
        opacity: 1;
        animation: unset;
        animation-delay: unset;
    }

    .fade-animation {
        animation: fadeInOut 4s infinite;
    }

    .fade-text {
        animation: fadeInOut 4s infinite;
    }

    @keyframes fadeInOut {
        0% { opacity: 0; }
        15% { opacity: 1; }
        85% { opacity: 1; }
        100% { opacity: 0; }
    }

    .preview * {
        cursor: default !important;
        pointer-events: none !important;
    }

    /* Add a class to stop the animation */
    .no-animation .fade-animation,
    .no-animation .fade-text {
        animation: none;
    }

    /* Styles for success view */
    .success-message {
        color: var(--color-success);
        text-align: center;
        margin-bottom: 20px;
        line-height: 1.5;
    }

    .continue-button {
        /* Inherit button styles or define specific ones */
        /* Example using existing button styles */
        padding: 10px 20px;
        background-color: var(--color-primary);
        color: white;
        border: none;
        border-radius: 5px;
        cursor: pointer;
        font-size: 16px;
        transition: background-color 0.2s;
        display: flex; /* For loading spinner alignment */
        justify-content: center;
        align-items: center;
        min-height: 40px; /* Ensure consistent height with loading spinner */
    }

    .continue-button:hover:not(:disabled) {
        background-color: var(--color-primary-dark);
    }

    .continue-button:disabled {
        background-color: var(--color-grey-light);
        cursor: not-allowed;
    }

    /* Loading spinner (reuse from login button if available) */
    .loading-spinner {
        border: 3px solid rgba(255, 255, 255, 0.3);
        border-radius: 50%;
        border-top: 3px solid white;
        width: 18px;
        height: 18px;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }


    @media (max-width: 600px) {
        .login-2fa {
            align-items: center;
        }

        .check-2fa-container, /* Adjust mobile margins */
        .app-name-container {
             margin: 10px 0 10px 0; 
        }
        .check-2fa-container.hidden,
        .app-name-container.hidden {
             margin: 0;
        }
        .app-name {
            margin-bottom: 10px; /* Reduce bottom margin on mobile */
        }

        .enter-backup-code {
            margin-top: 10px;
        }
    }
</style>