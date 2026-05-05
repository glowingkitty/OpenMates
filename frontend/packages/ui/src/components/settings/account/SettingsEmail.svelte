<!--
    Settings Email Component - Displays and changes the user's encrypted login
    email address. Uses the canonical Settings element set only; the account
    email salt is preserved so existing password and passkey login material
    remains valid after an email identity change.
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import * as cryptoService from '../../../services/cryptoService';
    import { copyToClipboard } from '../../../utils/clipboardUtils';
    import { notificationStore } from '../../../stores/notificationStore';
    import {
        SettingsButton,
        SettingsButtonGroup,
        SettingsCard,
        SettingsDetailRow,
        SettingsInfoBox,
        SettingsInput,
        SettingsLoadingState,
    } from '../elements';
    import SecurityAuth from '../security/SecurityAuth.svelte';

    type AuthSuccessData = {
        method: 'passkey' | 'password' | '2fa' | 'email_otp';
        credentialId?: string;
        tfaCode?: string;
        hashedEmail?: string;
        lookupHash?: string;
    };

    let email = $state<string | null>(null);
    let newEmail = $state('');
    let verificationCode = $state('');
    let isLoading = $state(true);
    let isCopied = $state(false);
    let codeSent = $state(false);
    let codeVerified = $state(false);
    let isRequestingCode = $state(false);
    let isVerifyingCode = $state(false);
    let isConfirming = $state(false);
    let errorMessage = $state<string | null>(null);
    let successMessage = $state<string | null>(null);
    let showAuthModal = $state(false);
    let hasPasskey = $state(false);
    let has2FA = $state(false);
    let hasPassword = $state(false);

    let normalizedNewEmail = $derived(newEmail.trim().toLowerCase());
    let canRequestCode = $derived(!!normalizedNewEmail && normalizedNewEmail !== email && !isRequestingCode);
    let canVerifyCode = $derived(codeSent && verificationCode.length === 6 && !isVerifyingCode);
    let canConfirmChange = $derived(codeVerified && !isConfirming);

    onMount(async () => {
        await Promise.all([loadEmail(), fetchAuthMethods()]);
    });

    async function loadEmail() {
        try {
            email = await cryptoService.getEmailDecryptedWithMasterKey();
        } catch (error) {
            console.error('[SettingsEmail] Error decrypting email:', error);
        } finally {
            isLoading = false;
        }
    }

    async function fetchAuthMethods() {
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.getUserAuthMethods), {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                hasPasskey = data.has_passkey || false;
                has2FA = data.has_2fa || false;
                hasPassword = data.has_password || false;
            }
        } catch (error) {
            console.error('[SettingsEmail] Error fetching auth methods:', error);
        }
    }

    async function handleCopyEmail() {
        if (!email) return;
        const result = await copyToClipboard(email);
        if (result.success) {
            isCopied = true;
            notificationStore.success($text('settings.account.email.copied'));
            setTimeout(() => { isCopied = false; }, 2000);
        } else {
            console.error('[SettingsEmail] Failed to copy email:', result.error);
        }
    }

    async function requestChangeCode() {
        if (!canRequestCode) return;
        isRequestingCode = true;
        errorMessage = null;
        successMessage = null;
        verificationCode = '';
        codeVerified = false;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.settings.user.requestEmailChangeCode), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ new_email: normalizedNewEmail })
            });
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.detail || data.message || 'Failed to send verification code');
            }
            codeSent = true;
            successMessage = $text('settings.account.email.change_code_sent');
        } catch (error) {
            errorMessage = error instanceof Error ? error.message : 'Failed to send verification code';
        } finally {
            isRequestingCode = false;
        }
    }

    async function verifyChangeCode() {
        if (!canVerifyCode) return;
        isVerifyingCode = true;
        errorMessage = null;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.settings.user.verifyEmailChangeCode), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ new_email: normalizedNewEmail, code: verificationCode })
            });
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.detail || data.message || 'Invalid verification code');
            }
            codeVerified = true;
            successMessage = $text('settings.account.email.change_code_verified');
        } catch (error) {
            verificationCode = '';
            errorMessage = error instanceof Error ? error.message : 'Invalid verification code';
        } finally {
            isVerifyingCode = false;
        }
    }

    function startConfirmChange() {
        if (!canConfirmChange) return;
        errorMessage = null;
        showAuthModal = true;
    }

    async function handleAuthSuccess(data: AuthSuccessData) {
        showAuthModal = false;
        try {
            await verifyRecentReauth(data);
            await confirmChange(data);
        } catch (error) {
            errorMessage = error instanceof Error ? error.message : 'Authentication verification failed';
        }
    }

    async function verifyRecentReauth(authData: AuthSuccessData) {
        const authMethod = authData.method === '2fa' ? '2fa_otp' : authData.method;
        const response = await fetch(getApiEndpoint(apiEndpoints.settings.user.reauthEmailChange), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                auth_method: authMethod,
                auth_code: authData.credentialId || authData.tfaCode || '',
                hashed_email: authData.hashedEmail,
                lookup_hash: authData.lookupHash
            })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.detail || data.message || 'Authentication verification failed');
        }
    }

    function handleAuthFailed(message: string) {
        showAuthModal = false;
        errorMessage = message;
    }

    function handleAuthCancel() {
        showAuthModal = false;
    }

    async function confirmChange(authData: AuthSuccessData) {
        isConfirming = true;
        errorMessage = null;
        successMessage = null;

        try {
            const emailSalt = cryptoService.getEmailSalt();
            if (!emailSalt) {
                throw new Error('Email salt not available. Please log in again.');
            }

            const emailEncryptionKey = await cryptoService.deriveEmailEncryptionKey(normalizedNewEmail, emailSalt);
            const encryptedEmail = await cryptoService.encryptEmail(normalizedNewEmail, emailEncryptionKey);
            const encryptedEmailWithMasterKey = await cryptoService.encryptWithMasterKey(normalizedNewEmail);
            if (!encryptedEmailWithMasterKey) {
                throw new Error('Could not encrypt email with master key. Please log in again.');
            }

            const hashedEmail = await cryptoService.hashEmail(normalizedNewEmail);
            const authMethod = authData.method === '2fa' ? '2fa_otp' : authData.method;
            const authCode = authData.credentialId || authData.tfaCode || '';

            const response = await fetch(getApiEndpoint(apiEndpoints.settings.user.confirmEmailChange), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    new_email: normalizedNewEmail,
                    hashed_email: hashedEmail,
                    encrypted_email_address: encryptedEmail,
                    encrypted_email_with_master_key: encryptedEmailWithMasterKey,
                    auth_method: authMethod,
                    auth_code: authCode
                })
            });
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.detail || data.message || 'Failed to change email');
            }

            const useLocalStorage = typeof window !== 'undefined'
                && window.localStorage.getItem('openmates_email_encryption_key') !== null;
            cryptoService.saveEmailEncryptionKey(emailEncryptionKey, useLocalStorage);
            await cryptoService.saveEmailEncryptedWithMasterKey(normalizedNewEmail, useLocalStorage);

            email = normalizedNewEmail;
            newEmail = '';
            verificationCode = '';
            codeSent = false;
            codeVerified = false;
            successMessage = $text('settings.account.email.change_success');
        } catch (error) {
            errorMessage = error instanceof Error ? error.message : 'Failed to change email';
        } finally {
            isConfirming = false;
        }
    }

    function handleCodeInput(value: string) {
        verificationCode = value.replace(/\D/g, '').slice(0, 6);
    }
</script>

{#if isLoading}
    <SettingsLoadingState text={$text('settings.account.email.loading')} />
{:else if email}
    <SettingsCard>
        <SettingsDetailRow
            label={$text('settings.account.email.current_email')}
            value={email}
            icon={isCopied ? 'icon_check' : 'icon_copy'}
        />
    </SettingsCard>

    <SettingsButtonGroup align="left">
        <SettingsButton variant="secondary" onClick={handleCopyEmail} dataTestid="copy-email-button">
            {$text('settings.account.email.copy_button')}
        </SettingsButton>
    </SettingsButtonGroup>

    <SettingsInfoBox type="info">
        {$text('settings.account.email.privacy_info')}
    </SettingsInfoBox>

    {#if successMessage}
        <SettingsInfoBox type="success">{successMessage}</SettingsInfoBox>
    {/if}
    {#if errorMessage}
        <SettingsInfoBox type="error">{errorMessage}</SettingsInfoBox>
    {/if}

    <SettingsInput
        bind:value={newEmail}
        type="email"
        placeholder={$text('settings.account.email.new_email_placeholder')}
        autocomplete="email"
        dataTestid="email-change-new-email"
        disabled={isRequestingCode || isVerifyingCode || isConfirming}
    />

    <SettingsButtonGroup align="left">
        <SettingsButton
            variant="secondary"
            onClick={requestChangeCode}
            disabled={!canRequestCode}
            loading={isRequestingCode}
            dataTestid="email-change-request-code"
        >
            {$text('settings.account.email.send_change_code')}
        </SettingsButton>
    </SettingsButtonGroup>

    {#if codeSent}
        <SettingsInput
            bind:value={verificationCode}
            type="text"
            inputmode="numeric"
            pattern="[0-9]*"
            maxlength={6}
            placeholder="000000"
            dataTestid="email-change-code"
            disabled={isVerifyingCode || isConfirming || codeVerified}
            onInput={handleCodeInput}
        />
        <SettingsButtonGroup align="left">
            <SettingsButton
                variant="secondary"
                onClick={verifyChangeCode}
                disabled={!canVerifyCode || codeVerified}
                loading={isVerifyingCode}
                dataTestid="email-change-verify-code"
            >
                {$text('settings.account.email.verify_change_code')}
            </SettingsButton>
            <SettingsButton
                onClick={startConfirmChange}
                disabled={!canConfirmChange}
                loading={isConfirming}
                dataTestid="email-change-confirm"
            >
                {$text('settings.account.email.confirm_change')}
            </SettingsButton>
        </SettingsButtonGroup>
    {/if}
{:else}
    <SettingsInfoBox type="error">{$text('settings.account.email.error_decrypting')}</SettingsInfoBox>
{/if}

{#if showAuthModal}
    <SecurityAuth
        {hasPasskey}
        {hasPassword}
        has2FA={has2FA}
        title={$text('settings.account.email.auth_title')}
        description={$text('settings.account.email.auth_description')}
        autoStart={true}
        onSuccess={handleAuthSuccess}
        onFailed={handleAuthFailed}
        onCancel={handleAuthCancel}
    />
{/if}
