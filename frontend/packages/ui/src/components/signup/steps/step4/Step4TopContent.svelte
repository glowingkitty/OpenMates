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
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { 
        twoFASetupData, 
        twoFASetupComplete, 
        setTwoFAData,
        resetTwoFAData
    } from '../../../../stores/twoFAState';

    let showQrCode = false;
    let showCopiedText = false;
    let loading = true;
    let error = false;
    let errorMessage = '';
    
    // Reactive variables bound to store values
    $: secret = $twoFASetupData.secret;
    $: qrCodeUrl = $twoFASetupData.qrCodeUrl;
    $: otpauthUrl = $twoFASetupData.otpauthUrl;
    $: setupComplete = $twoFASetupComplete;

    // Reset the store when component mounts
    onMount(() => {
        resetTwoFAData();
    });

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
    <div class="prevent-access-text" class:fade-out={showQrCode}>
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

    {#if showQrCode && qrCodeUrl}
    <div class="qr-code" transition:fade style="background-image: url('{qrCodeUrl}')">
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
            <button class="text-button with-icon" on:click={toggleQrCode} disabled={!qrCodeUrl}>
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
    {/if}
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
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        position: absolute;
        top: 50%;
        transform: translateY(-20px);
        z-index: 1;
    }

    @media (prefers-color-scheme: dark) {
        .qr-code {
            filter: invert(1);
        }
    }

    .fade-out {
        opacity: 0;
        pointer-events: none;
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
