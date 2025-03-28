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
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { onMount } from 'svelte';
    import { get } from 'svelte/store'; // Import get
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { isResettingTFA } from '../../../../stores/signupState'; // Import store
    import { userProfile } from '../../../../stores/userProfile'; // Import userProfile store
    import { 
        twoFASetupData, 
        twoFASetupComplete,
        setTwoFAData,
        resetTwoFAData // Ensure reset function is imported
    } from '../../../../stores/twoFAState';
    import { theme } from '../../../../stores/theme';
    import QRCode from 'qrcode-svg';

    let showQrCode = false;
    let showCopiedText = false;
    let loading = true;
    let error = false;
    let errorMessage = '';
    let qrCodeSvg = '';
    
    // Reactive variables bound to store values
    $: secret = $twoFASetupData.secret;
    $: otpauthUrl = $twoFASetupData.otpauthUrl;
    $: setupComplete = $twoFASetupComplete;
    $: updateQrCodeColor($theme, otpauthUrl);

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
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.setup_2fa), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
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
        }
    }

    function toggleQrCode() {
        showQrCode = !showQrCode;
    }

    async function copySecret() {
        if (!secret) return;
        
        await navigator.clipboard.writeText(secret);
        showCopiedText = true;

        // Reset copied text after 2 seconds
        setTimeout(() => {
            showCopiedText = false;
        }, 2000);
    }

    function retrySetup() {
        resetTwoFAData();
    }

    // Handle the reset button click
    async function handleResetTFA() {
        resetTwoFAData(); // Clear old data
        isResettingTFA.set(false); // Set flag to false immediately to show loading/content
        await fetchSetup2FA(); // Fetch new data
    }
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size tfa"></div>
        <h2 class="signup-menu-title">{@html $text('signup.secure_your_account.text')}</h2>
    </div>
    
    {#if !setupComplete}
    <div class="prevent-access-text">
        {$text('signup.prevent_access.text')}
    </div>
    
    <div class="features">
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
    <div class="prevent-access-text" class:fade-out={showQrCode && !$isResettingTFA}>
        {$text('signup.prevent_access.text')}
    </div>
    
    <div class="features" class:fade-out={showQrCode}>
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
    {#if $isResettingTFA}
        <!-- Reset View: Reset Button -->
        <div class="action-buttons">
             <div class="button-row">
                 <button class="text-button with-icon" on:click={handleResetTFA}>
                    <span class="button-icon restore-icon"></span> <!-- Assuming a restore/reset icon exists -->
                    <span>{@html $text('signup.reset_tfa.text')}</span>
                </button>
             </div>
        </div>
    {:else if setupComplete}
        <!-- Standard Actions (only if NOT resetting AND setup is complete) -->
        {#if showQrCode}
        <div class="qr-code" transition:fade>
            <!-- Use the SVG string directly -->
            {@html qrCodeSvg}
        </div>
        {/if}

        <div class="action-buttons">
            <div class="button-row" class:move-up={showQrCode}>
                <button class="text-button with-icon" on:click={handleDeepLink} disabled={!otpauthUrl}>
                    <span class="button-icon open-icon"></span>
                    <span>{@html $text('signup.add_to_2fa_app.text')}</span>
                </button>
            </div>
            
            <div class="button-row" class:move-up={showQrCode}>
                <span class="or-text">{@html $text('signup.or.text')}</span>
                <button class="text-button with-icon" on:click={toggleQrCode} disabled={!qrCodeSvg}>
                    <span class="button-icon camera-icon"></span>
                    <span>{@html $text('signup.scan_via_2fa_app.text')}</span>
                </button>
            </div>

            <div class="button-row">
                <span class="or-text">{@html $text('signup.or.text')}</span>
                <button class="text-button with-icon" on:click={copySecret} disabled={!secret}>
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
        </div>
    {/if} <!-- End of outer {:else if setupComplete} -->
</div>

<style>
    :root {
        --qr-code-size: 150px;
    }

    .content {
        padding: 24px;
        height: 100%;
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
        transition: opacity 0.3s ease;
    }

    .fade-out {
        opacity: 0;
        pointer-events: none;
    }

    .features {
        display: flex;
        gap: 32px;
        justify-content: center;
        align-items: flex-start;
        transition: opacity 0.3s ease;
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
        width: 35px;
        height: 35px;
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
        transform: translateY(-20px);
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

    .primary-button {
        background-color: var(--color-primary);
        color: white;
        border: none;
        border-radius: 4px;
        padding: 8px 16px;
        cursor: pointer;
        font-weight: 500;
        transition: background-color 0.2s;
    }

    .primary-button:hover {
        background-color: var(--color-primary-dark, #0056b3);
    }

    .text-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
</style>
