<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_4_top_content_svelte:
    tfa_explainer:
        type: 'text + visuals'
        text:
            - $text('signup.secure_your_account.text')
            - $text('signup.prevent_access.text')
            - $text('signup.free.text')
            - $text('signup.fast_to_setup.text')
            - $text('signup.max_security.text')
        visuals:
            - 'Three checkmark icons. One for each of the three features (free, fast to setup, max security)'
        purpose:
            - 'Informs user about the advantages of securing their account with 2FA'
            - 'Reminds users 2FA is free, fast to setup, and provides maximum security'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
        connected_documentation:
            - '/signup/2fa'
    add_to_2fa_app_button:
        type: 'button'
        text: $text('signup.add_to_2fa_app.text')
        purpose:
            - 'Uses deep linking to open the 2FA app on the user device and add the user account to the 2FA app'
        processing:
            - 'User clicks the button'
            - 'User is forwarded to the 2FA app'
            - 'User account is automatically added to the 2FA app'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
        connected_documentation:
            - '/signup/2fa'
    scan_via_2fa_app_button:
        type: 'button'
        text: $text('signup.scan_via_2fa_app.text')
        purpose:
            - 'Opens the QR code for the user to scan with their 2FA app, to add the user account to the 2FA app'
        processing:
            - 'User clicks the button'
            - 'QR code is shown'
            - 'User scans the QR code with their 2FA app'
            - 'User account is added to the 2FA app'
            - 'If user clicks button second time, QR code is hidden'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
            - 'QR code'
        connected_documentation:
            - '/signup/2fa'
    copy_secret_button:
        type: 'button'
        text: $text('signup.copy_secret.text')
        purpose:
            - 'Copies the secret key to the user clipboard, to manually add the user account to the 2FA app'
        processing:
            - 'User clicks the button'
            - 'Secret key is copied to the user clipboard'
            - 'User sees a confirmation message that the secret key was copied'
            - 'User pastes the secret key into the 2FA app'
            - 'User account is added to the 2FA app'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - '2fa'
        connected_documentation:
            - '/signup/2fa'
-->

<script lang="ts">
    /**
     * One Time Codes Top Content Component
     *
     * This component handles:
     * - Setting up 2FA for the user account
     * - Displaying QR code for 2FA app setup
     * - Sending the email encryption key to the server for notification emails
     *
     * Security Flow:
     * 1. Decrypt the email on demand using the master key (not from the store)
     * 2. Get the email encryption key from storage
     * 3. Send the email encryption key to the server for temporary use
     * 4. The server uses the key to decrypt the email for notification purposes
     * 5. The server immediately discards the key after use
     *
     * This component follows the "decrypt on demand" approach, where the email
     * is always decrypted from storage when needed rather than being stored in plaintext.
     */
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { onMount, createEventDispatcher } from 'svelte';
    import { get } from 'svelte/store'; // Import get
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { userProfile } from '../../../../stores/userProfile'; // Import userProfile store
    import {
        twoFASetupData,
        twoFASetupComplete,
        setTwoFAData,
        resetTwoFAData // Ensure reset function is imported
    } from '../../../../stores/twoFAState';
    import { theme } from '../../../../stores/theme';
    import QRCode from 'qrcode-svg';
    import { signupStore } from '../../../../stores/signupStore'; // Import signupStore for email
    import * as cryptoService from '../../../../services/cryptoService'; // Import cryptoService for email encryption
    import { copyToClipboard } from '../../../../utils/clipboardUtils'; // Safari-compatible clipboard

    // State variables using Svelte 5 runes
    let showQrCode = $state(false);
    let showCopiedText = $state(false);
    let showSecretCode = $state(false);  // Shows the secret code for manual copying
    let loading = $state(true);
    let error = $state(false);
    let errorMessage = $state('');
    let qrCodeSvg = $state('');

    const dispatch = createEventDispatcher();
    
    // Reactive variables bound to store values using Svelte 5 runes
    let secret = $derived($twoFASetupData.secret);
    let otpauthUrl = $derived($twoFASetupData.otpauthUrl);
    let setupComplete = $derived($twoFASetupComplete);
    
    // Update QR code color when theme or URL changes using Svelte 5 runes
    $effect(() => {
        updateQrCodeColor($theme, otpauthUrl);
    });

    // Function to regenerate QR code when theme changes
    function updateQrCodeColor(currentTheme, url) {
        if (!url) return;
        
        const color = currentTheme === 'dark' ? '#FFFFFF' : '#000000';
        const bgColor = 'transparent';
        
        try {
            const qr = new QRCode({
                content: url,
                padding: 0,
                width: 150,
                height: 150,
                color: color,
                background: bgColor,
                ecl: 'M'  // Error correction level
            });
            
            qrCodeSvg = qr.svg();
        } catch (err) {
            console.error('Error generating QR code:', err);
        }
    }

    // Fetch 2FA setup data when component mounts, if TFA is not already enabled
    onMount(async () => {
        // Get the current profile state once on mount
        const profile = get(userProfile);

        // Check if profile is loaded and tfa is not enabled
        if (profile && !profile.tfa_enabled) {
            // Fetch setup data only if TFA is not enabled
            await fetchSetup2FA();
        }
    });

    // Fetch 2FA setup data from the API
    async function fetchSetup2FA() {
        loading = true;
        error = false;
        errorMessage = '';
        
        try {
            // Get email from encrypted storage (always decrypt on demand)
            // CRITICAL: Must await since getEmailDecryptedWithMasterKey is async
            const email = await cryptoService.getEmailDecryptedWithMasterKey();
            
            // If we can't get the email, we can't proceed
            if (!email) {
                console.error('Could not retrieve email from encrypted storage');
                error = true;
                errorMessage = 'Could not retrieve account information';
                loading = false;
                return;
            }
            
            // Prepare request body
            const requestBody: any = {};
            
            // Get the email encryption key from storage
            // This key was saved during password setup and is needed for the backend to decrypt the email
            const emailEncryptionKeyBase64 = cryptoService.getEmailEncryptionKeyForApi();
            
            // Add email encryption key if available
            if (emailEncryptionKeyBase64) {
                requestBody.email_encryption_key = emailEncryptionKeyBase64;
            } else {
                console.error('Email encryption key not found in storage - cannot send to backend for email decryption');
                error = true;
                errorMessage = 'Could not retrieve encryption key';
                loading = false;
                return;
            }
            
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.setup_2fa), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestBody),
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // Update the store with the 2FA setup data
                setTwoFAData(
                    data.secret,
                    '',  // We don't need the QR code URL anymore as we generate SVG
                    data.otpauth_url
                );
                
                // Generate SVG QR code
                updateQrCodeColor($theme, data.otpauth_url);
            } else {
                error = true;
                errorMessage = data.message || 'Failed to set up 2FA';
                console.error('Failed to set up 2FA:', data.message);
            }
        } catch (err) {
            error = true;
            errorMessage = 'An error occurred while setting up 2FA';
            console.error('Error setting up 2FA:', err);
        } finally {
            loading = false;
        }
    }

    function handleDeepLink() {
        if (otpauthUrl) {
            window.location.href = otpauthUrl;
            dispatch('actionClicked'); // Dispatch event
        }
    }

    function toggleQrCode() {
        showQrCode = !showQrCode;
        // Hide secret code when showing QR code (mutually exclusive to avoid overlap)
        if (showQrCode) {
            showSecretCode = false;
        }
        dispatch('actionClicked'); // Dispatch event
    }

    /**
     * Copy the 2FA secret to clipboard.
     * Uses Safari-compatible clipboard utility with fallback for older browsers.
     * Always shows the secret code in the UI so user can manually select/copy if needed.
     */
    async function copySecret() {
        if (!secret) return;
        
        // Hide QR code when showing secret code (mutually exclusive to avoid overlap)
        showQrCode = false;
        // Always show the secret code so user can manually copy if needed
        showSecretCode = true;
        dispatch('actionClicked'); // Dispatch event
        
        const result = await copyToClipboard(secret);
        
        if (result.success) {
            showCopiedText = true;

            // Reset copied text after 2 seconds (but keep secret visible)
            setTimeout(() => {
                showCopiedText = false;
            }, 2000);
        } else {
            // Clipboard failed - secret is still visible for manual copying
            console.warn('[OneTimeCodesTopContent] Clipboard copy failed, secret displayed for manual copy');
        }
    }
    
    /**
     * Toggle visibility of the secret code display.
     */
    function toggleSecretCode() {
        showSecretCode = !showSecretCode;
    }

    function retrySetup() {
        resetTwoFAData();
    }

    // Handle the reset button click
    async function handleResetTFA() {
        resetTwoFAData(); // Clear old data
        // isResettingTFA.set(false); // No longer needed
        await fetchSetup2FA(); // Fetch new data
    }
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size tfa"></div>
        <h2 class="signup-menu-title">{@html $text('signup.one_time_codes.text')}</h2>
    </div>
    
    {#if !setupComplete}
    <!-- Hide prevent-access-text when showing secret code so user can see the key for manual copying -->
    <div class="prevent-access-text" class:fade-out={showSecretCode}>
        {$text('signup.prevent_access.text')}
    </div>
    
    <!-- Hide features when showing secret code so user can see the key for manual copying -->
    <div class="features" class:fade-out={showSecretCode}>
        <div class="feature">
            <div class="check-icon"></div>
            <span>{@html $text('signup.free.text')}</span>
        </div>
        <div class="feature">
            <div class="check-icon"></div>
            <span>{@html $text('signup.fast_to_setup.text')}</span>
        </div>
        <div class="feature">
            <div class="check-icon"></div>
            <span>{@html $text('signup.max_security.text')}</span>
        </div>
    </div>
    {:else} 
    <!-- This block executes when setup IS complete -->
    <!-- Hide prevent-access-text when showing QR code OR secret code so user can see the relevant content -->
    <div class="prevent-access-text" class:fade-out={(showQrCode || showSecretCode) && !$userProfile.tfa_enabled}>
        {$text('signup.prevent_access.text')}
    </div>
    
    <!-- Hide features when showing QR code OR secret code so user can see the relevant content -->
    <div class="features" class:fade-out={(showQrCode || showSecretCode) && !$userProfile.tfa_enabled}>
        <div class="feature">
            <div class="check-icon"></div>
            <span>{@html $text('signup.free.text')}</span>
        </div>
        <div class="feature">
            <div class="check-icon"></div>
            <span>{@html $text('signup.fast_to_setup.text')}</span>
        </div>
        <div class="feature">
            <div class="check-icon"></div>
            <span>{@html $text('signup.max_security.text')}</span>
        </div>
    </div>
    {/if} <!-- End of {#if !setupComplete}{:else} block -->

    <!-- Separate block for action/reset buttons -->
    {#if $userProfile.tfa_enabled}
        <!-- Reset View: Reset Button -->
        <div class="action-buttons">
             <div class="button-row">
                 <button class="text-button with-icon" onclick={handleResetTFA}>
                    <span class="button-icon restore-icon"></span> <!-- Assuming a restore/reset icon exists -->
                    <span>{@html $text('signup.reset_tfa.text')}</span>
                </button>
             </div>
        </div>
    {/if} 

    {#if !$userProfile.tfa_enabled && setupComplete}
        <!-- Standard Actions (only if NOT resetting AND setup is complete) -->
        {#if showQrCode}
        <div class="qr-code" transition:fade>
            <!-- Use the SVG string directly -->
            {@html qrCodeSvg}
        </div>
        {/if}

        <div class="action-buttons">
            <div class="button-row" class:move-up={showQrCode}>
                <button class="text-button with-icon" onclick={handleDeepLink} disabled={!otpauthUrl}>
                    <span class="button-icon open-icon"></span>
                    <span>{@html $text('signup.add_to_2fa_app.text')}</span>
                </button>
            </div>
            
            <div class="button-row" class:move-up={showQrCode}>
                <span class="or-text">{@html $text('signup.or.text')}</span>
                <button class="text-button with-icon" onclick={toggleQrCode} disabled={!qrCodeSvg}>
                    <span class="button-icon camera-icon"></span>
                    <span>{@html $text('signup.scan_via_2fa_app.text')}</span>
                </button>
            </div>

            <div class="button-row">
                <span class="or-text">{@html $text('signup.or.text')}</span>
                <button class="text-button with-icon" onclick={copySecret} disabled={!secret}>
                    <span class="button-icon copy-icon"></span>
                    <span>
                        {#if showCopiedText}
                            {$text('enter_message.press_and_hold_menu.copied_to_clipboard.text')}
                        {:else}
                            {$text('signup.copy_secret.text')}
                        {/if}
                    </span>
                </button>
            </div>
            
            <!-- Secret code display - shown when user clicks copy for manual selection -->
            {#if showSecretCode && secret}
            <div class="secret-code-container" transition:fade>
                <div class="secret-code-label">{$text('signup.your_secret_key.text')}</div>
                <input 
                    type="text" 
                    class="secret-code-input" 
                    value={secret} 
                    readonly 
                    onclick={(e) => e.currentTarget.select()}
                    aria-label="2FA Secret Key"
                />
                <button class="hide-secret-button" onclick={toggleSecretCode}>
                    {$text('signup.hide_secret.text')}
                </button>
            </div>
            {/if}
        </div>
    {/if} <!-- End of outer {:else if setupComplete} -->
</div>

<style>
    :root {
        --qr-code-size: 150px;
    }

    .content {
        padding: 24px;
        height: auto;
        min-height: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
    }

    .signup-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 16px;
    }

    .prevent-access-text {
        margin: 20px 0 20px 0;
        text-align: center;
        /* Transition all properties for smooth collapse animation */
        transition: opacity 0.3s ease, max-height 0.3s ease, margin 0.3s ease;
        max-height: 100px; /* Enough height for the text */
        overflow: hidden;
    }

    .fade-out {
        opacity: 0;
        pointer-events: none;
        /* Collapse the element so content below moves up */
        max-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: hidden;
    }

    .features {
        display: flex;
        gap: 32px;
        justify-content: center;
        align-items: flex-start;
        /* Transition all properties for smooth collapse animation */
        transition: opacity 0.3s ease, max-height 0.3s ease, margin 0.3s ease, gap 0.3s ease;
        max-height: 200px; /* Enough height for the features */
        overflow: hidden;
    }

    .feature {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        width: 110px;
        text-align: center;
    }

    .check-icon {
        width: 20px;
        height: 20px;
        -webkit-mask: url('@openmates/ui/static/icons/check.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/check.svg') no-repeat center;
        -webkit-mask-size: contain;
        mask-size: contain;
        background-color: #58BC00;
    }

    .action-buttons {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        margin-top: 20px;
        position: relative;
        width: 100%;
    }

    .button-row {
        display: flex;
        align-items: center;
        gap: 8px;
        position: relative;
        transition: transform 0.3s ease;
    }

    .button-row.move-up {
        transform: translateY(calc(var(--qr-code-size) * -1));
    }

    .or-text {
        color: var(--color-grey-60);
        position: absolute;
        right: 100%;
        margin-right: 8px;
        white-space: nowrap;
    }

    .text-button.with-icon {
        display: flex;
        gap: 8px;
    }

    .button-icon {
        width: 20px;
        height: 20px;
        -webkit-mask-size: contain !important;
        mask-size: contain !important;
        background-image: var(--color-primary);
    }

     /* Added restore icon style */
    .restore-icon {
        -webkit-mask: url('@openmates/ui/static/icons/restore.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/restore.svg') no-repeat center;
    }

    .open-icon {
        -webkit-mask: url('@openmates/ui/static/icons/open.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/open.svg') no-repeat center;
    }

    .camera-icon {
        -webkit-mask: url('@openmates/ui/static/icons/camera.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/camera.svg') no-repeat center;
    }

    .copy-icon {
        -webkit-mask: url('@openmates/ui/static/icons/copy.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/copy.svg') no-repeat center;
    }

    .qr-code {
        width: var(--qr-code-size);
        height: var(--qr-code-size);
        position: absolute;
        top: 50%;
        transform: translateY(-28px);
        z-index: 1;
        display: flex;
        justify-content: center;
        align-items: center;
    }

    /* Remove dark mode inversion as we handle color via JS */
    @media (prefers-color-scheme: dark) {
        .qr-code {
            filter: none;
        }
    }

    /* Added media query for screens 600px and smaller */
    @media (max-width: 600px) {
        .features {
            width: 100%;
            gap: 5px;
        }

        .prevent-access-text {
            margin: 10px 0 10px 0;
        }
        
        .feature {
            flex: 1;
            width: auto;
            min-width: 0;
        }

        .action-buttons {
            margin-top: 10px;
        }
    }


    .text-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    /* Secret code display for manual copying */
    .secret-code-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        margin-top: 16px;
        padding: 16px;
        border-radius: 8px;
        width: 100%;
        max-width: 320px;
    }

    .secret-code-label {
        font-size: 12px;
        color: var(--color-text-secondary, #666);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .secret-code-input {
        width: 100%;
        padding: 12px;
        font-family: 'Courier New', Courier, monospace;
        font-size: 14px;
        font-weight: bold;
        letter-spacing: 1px;
        text-align: center;
        background: var(--color-grey-10);
        border: 2px dashed var(--color-grey-50, #ccc);
        border-radius: 6px;
        color: var(--color-grey-100);
        cursor: text;
        /* Allow text selection for manual copying */
        user-select: all;
        -webkit-user-select: all;
    }

    .secret-code-input:focus {
        outline: none;
        border-color: var(--color-primary, #007bff);
    }

    .hide-secret-button {
        padding: 6px 12px;
        font-size: 12px;
        color: var(--color-text-secondary, #666);
        background: transparent;
        border: none;
        cursor: pointer;
        text-decoration: underline;
    }

    .hide-secret-button:hover {
        color: var(--color-text-primary, #333);
    }
</style>
