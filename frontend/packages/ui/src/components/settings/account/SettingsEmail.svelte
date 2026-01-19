<!--
    Settings Email Component - Displays the user's decrypted email address
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getEmailDecryptedWithMasterKey } from '../../../services/cryptoService';
    import SettingsItem from '../../SettingsItem.svelte';

    let email = $state<string | null>(null);
    let isLoading = $state(true);

    onMount(async () => {
        try {
            email = await getEmailDecryptedWithMasterKey();
        } catch (error) {
            console.error('[SettingsEmail] Error decrypting email:', error);
        } finally {
            isLoading = false;
        }
    });
</script>

<div class="settings-email">
    {#if isLoading}
        <div class="loading">{$text('settings.account.email.loading.text')}</div>
    {:else if email}
        <SettingsItem
            type="nested"
            icon="mail"
            title={$text('settings.account.email.current_email.text')}
            subtitleTop={email}
        />
        
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
