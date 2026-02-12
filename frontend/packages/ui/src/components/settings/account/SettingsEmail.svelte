<!--
    Settings Email Component - Displays the user's decrypted email address
    with a copy-to-clipboard button
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getEmailDecryptedWithMasterKey } from '../../../services/cryptoService';
    import { copyToClipboard } from '../../../utils/clipboardUtils';
    import { notificationStore } from '../../../stores/notificationStore';

    let email = $state<string | null>(null);
    let isLoading = $state(true);
    let isCopied = $state(false);

    onMount(async () => {
        try {
            email = await getEmailDecryptedWithMasterKey();
        } catch (error) {
            console.error('[SettingsEmail] Error decrypting email:', error);
        } finally {
            isLoading = false;
        }
    });

    /** Copy email address to clipboard */
    async function handleCopyEmail() {
        if (!email) return;
        const result = await copyToClipboard(email);
        if (result.success) {
            isCopied = true;
            notificationStore.success($text('settings.account.email.copied.text'));
            setTimeout(() => { isCopied = false; }, 2000);
        } else {
            console.error('[SettingsEmail] Failed to copy email:', result.error);
        }
    }
</script>

<div class="settings-email">
    {#if isLoading}
        <div class="loading">{$text('settings.account.email.loading.text')}</div>
    {:else if email}
        <!-- Email display row with icon, text, and copy button -->
        <div class="email-row">
            <div class="email-left">
                <div class="icon-container">
                    <div class="icon settings_size mail"></div>
                </div>
                <div class="email-text">
                    <div class="email-label">{$text('settings.account.email.current_email.text')}</div>
                    <div class="email-address">{email}</div>
                </div>
            </div>
            <button
                class="copy-button"
                onclick={handleCopyEmail}
                aria-label="Copy email address"
            >
                <div
                    class="clickable-icon"
                    class:icon_copy={!isCopied}
                    class:icon_check={isCopied}
                    style="width: 20px; height: 20px"
                ></div>
            </button>
        </div>

        <div class="info-box">
            <p>{$text('settings.account.email.privacy_info.text')}</p>
        </div>
    {:else}
        <div class="error">{$text('settings.account.email.error_decrypting.text')}</div>
    {/if}
</div>

<style>
    .settings-email {
        padding: 0;
    }

    .loading, .error {
        padding: 1.5rem;
        text-align: center;
        color: var(--color-text-secondary);
    }

    .error {
        color: var(--color-error);
    }

    /* Email row - matches SettingsItem layout */
    .email-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 5px 10px;
        border-radius: 8px;
        min-height: 40px;
    }

    .email-left {
        display: flex;
        align-items: center;
        flex: 1;
        min-width: 0;
    }

    .icon-container {
        width: 44px;
        height: 44px;
        margin-right: 12px;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .email-text {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
    }

    .email-label {
        font-size: 14px;
        color: var(--color-grey-60);
        text-align: left;
    }

    .email-address {
        font-size: 16px;
        font-weight: 500;
        color: var(--color-grey-100);
        text-align: left;
        word-break: break-all;
    }

    /* Copy button */
    .copy-button {
        background: none;
        border: none;
        cursor: pointer;
        padding: 8px;
        border-radius: 6px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: background-color 0.2s ease;
    }

    .copy-button:hover {
        background-color: var(--color-grey-10);
    }

    .copy-button:active {
        background-color: var(--color-grey-20);
    }

    .info-box {
        margin: 1.5rem;
        padding: 1rem;
        background: var(--color-background-secondary);
        border-radius: 8px;
        border: 1px solid var(--color-border);
    }

    .info-box p {
        margin: 0;
        font-size: 0.9rem;
        line-height: 1.5;
        color: var(--color-text-secondary);
    }
</style>
