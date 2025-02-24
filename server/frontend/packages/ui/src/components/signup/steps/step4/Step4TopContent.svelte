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
    
    {#if !showQrCode}
    <div class="prevent-access-text" transition:fade>
        {$_('signup.prevent_access.text')}
    </div>
    
    <div class="features" transition:fade>
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
    {/if}

    {#if showQrCode}
    <div class="qr-code" transition:fade style="background-image: url('data:image/svg+xml,...')">
    </div>
    {/if}

    <div class="action-buttons">
        <button class="text-button with-icon" on:click={handleDeepLink}>
            <span class="button-icon open-icon"></span>
            <span>{$_('signup.add_to_2fa_app.text')}</span>
        </button>
        
        <div class="button-row">
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
    }

    .features {
        display: flex;
        gap: 32px;
        justify-content: center;
        align-items: flex-start;
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
    }

    .button-row {
        display: flex;
        align-items: center;
        gap: 8px;
        position: relative;
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
        width: 200px;
        height: 200px;
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        margin: 24px 0;
    }
</style>
