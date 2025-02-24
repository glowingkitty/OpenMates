<!--
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
tfa_explainer:
    type: 'text + visuals'
    text:
        - $_('signup.secure_your_account.text')
        - $_('signup.prevent_access.text')
        - $_('signup.free.text')
        - $_('signup.fast_to_setup.text')
        - $_('signup.max_security.text')
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
    text: $_('signup.add_to_2fa_app.text')
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
    text: $_('signup.scan_via_2fa_app.text')
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
    text: $_('signup.copy_secret.text')
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
    import { _ } from 'svelte-i18n';
    import { fade } from 'svelte/transition';

    let showQrCode = false;
    let showCopiedText = false;
    const dummySecret = 'JBSWY3DPEHPK3PXP';
    const dummyUri = `otpauth://totp/OpenMates:user@example.com?secret=${dummySecret}&issuer=OpenMates`;

    function handleDeepLink() {
        window.location.href = dummyUri;
    }

    function toggleQrCode() {
        showQrCode = !showQrCode;
    }

    async function copySecret() {
        await navigator.clipboard.writeText(dummySecret);
        showCopiedText = true;

        // Reset copied text after 2 seconds
        setTimeout(() => {
            showCopiedText = false;
        }, 2000);
    }
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size tfa"></div>
        <h2 class="menu-title">{$_('signup.secure_your_account.text')}</h2>
    </div>
    
    <div class="prevent-access-text" class:fade-out={showQrCode}>
        {$_('signup.prevent_access.text')}
    </div>
    
    <div class="features" class:fade-out={showQrCode}>
        <div class="feature">
            <div class="check-icon"></div>
            <span>{$_('signup.free.text')}</span>
        </div>
        <div class="feature">
            <div class="check-icon"></div>
            <span>{$_('signup.fast_to_setup.text')}</span>
        </div>
        <div class="feature">
            <div class="check-icon"></div>
            <span>{$_('signup.max_security.text')}</span>
        </div>
    </div>

    {#if showQrCode}
    <div class="qr-code" transition:fade>
    </div>
    {/if}

    <div class="action-buttons">
        <div class="button-row" class:move-up={showQrCode}>
            <button class="text-button with-icon" on:click={handleDeepLink}>
                <span class="button-icon open-icon"></span>
                <span>{$_('signup.add_to_2fa_app.text')}</span>
            </button>
        </div>
        
        <div class="button-row" class:move-up={showQrCode}>
            <span class="or-text">{$_('signup.or.text')}</span>
            <button class="text-button with-icon" on:click={toggleQrCode}>
                <span class="button-icon camera-icon"></span>
                <span>{$_('signup.scan_via_2fa_app.text')}</span>
            </button>
        </div>

        <div class="button-row">
            <span class="or-text">{$_('signup.or.text')}</span>
            <button class="text-button with-icon" on:click={copySecret}>
                <span class="button-icon copy-icon"></span>
                <span>
                    {#if showCopiedText}
                        {$_('enter_message.press_and_hold_menu.copied_to_clipboard.text')}
                    {:else}
                        {$_('signup.copy_secret.text')}
                    {/if}
                </span>
            </button>
        </div>
    </div>
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

    .icon.header_size {
        width: 65px;
        height: 65px;
        border-radius: 14px;
        transition: none;
        animation: none;
        opacity: 1;
    }

    .menu-title {
        font-size: 24px;
        color: var(--color-grey-100);
        margin: 0;
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
        background-image: url('@openmates/ui/static/icons/dummyqr.svg');
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
</style>
