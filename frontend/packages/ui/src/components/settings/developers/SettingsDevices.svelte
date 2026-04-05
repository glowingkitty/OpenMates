<!--
SettingsDevices - Manage API key devices (approve/revoke devices that use API keys)
-->

<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint } from '../../../config/api';
    import SettingsInput from '../elements/SettingsInput.svelte';
    import { encryptWithMasterKey, decryptWithMasterKey } from '../../../services/cryptoService';

    const _dispatch = createEventDispatcher();

    // State using Svelte 5 $state() runes
    let devices = $state<Array<{
        id: string;
        api_key_id: string;
        anonymized_ip: string;
        country_code?: string;
        region?: string;
        city?: string;
        approved_at?: string;
        first_access_at?: string;
        last_access_at?: string;
        access_type: string;
        machine_identifier?: string;
        encrypted_device_name?: string;
        device_name?: string | null; // Decrypted device name for display
    }>>([]);
    let loading = $state(true);
    let error = $state<string>('');
    let processingDeviceId = $state<string | null>(null);
    let editingDeviceId = $state<string | null>(null);
    let editingDeviceName = $state('');

    // Load devices on mount
    onMount(() => {
        loadDevices();
    });

    async function loadDevices() {
        try {
            loading = true;
            error = '';
            const response = await fetch(getApiEndpoint('/v1/settings/api-key-devices'), {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'include' // Include cookies for authentication
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to load devices');
            }

            const data = await response.json();
            const rawDevices = data.devices || [];
            
            // Decrypt device names client-side using master key
            const decryptedDevices = [];
            for (const device of rawDevices) {
                let deviceName = null;
                if (device.encrypted_device_name) {
                    // Decrypt device name using master key (client-side only)
                    deviceName = await decryptWithMasterKey(device.encrypted_device_name);
                    if (!deviceName) {
                        console.warn(`[SettingsDevices] Failed to decrypt device name for device ${device.id}`);
                    }
                }
                decryptedDevices.push({
                    ...device,
                    device_name: deviceName
                });
            }
            devices = decryptedDevices;
        } catch (err: any) {
            console.error('Error loading devices:', err);
            error = err.message || 'Failed to load devices';
        } finally {
            loading = false;
        }
    }

    async function approveDevice(deviceId: string) {
        try {
            processingDeviceId = deviceId;
            error = '';
            const response = await fetch(getApiEndpoint(`/v1/settings/api-key-devices/${deviceId}/approve`), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'include'
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to approve device');
            }

            // Reload devices after approval
            await loadDevices();
        } catch (err: any) {
            console.error('Error approving device:', err);
            error = err.message || 'Failed to approve device';
        } finally {
            processingDeviceId = null;
        }
    }

    async function revokeDevice(deviceId: string) {
        if (!confirm($text('settings.developers_devices_confirm_revoke'))) {
            return;
        }

        try {
            processingDeviceId = deviceId;
            error = '';
            const response = await fetch(getApiEndpoint(`/v1/settings/api-key-devices/${deviceId}/revoke`), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'include'
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to revoke device');
            }

            // Reload devices after revocation
            await loadDevices();
        } catch (err: any) {
            console.error('Error revoking device:', err);
            error = err.message || 'Failed to revoke device';
        } finally {
            processingDeviceId = null;
        }
    }

    function formatDate(dateString: string | null): string {
        if (!dateString) return '-';
        try {
            const date = new Date(dateString);
            return date.toLocaleString();
        } catch {
            return dateString;
        }
    }

    function getAccessTypeLabel(accessType: string): string {
        const labels: Record<string, string> = {
            'rest_api': $text('settings.developers_devices_access_type_rest_api'),
            'cli': $text('settings.developers_devices_access_type_cli'),
            'pip': $text('settings.developers_devices_access_type_pip'),
            'npm': $text('settings.developers_devices_access_type_npm')
        };
        return labels[accessType] || accessType;
    }

    // Start editing a device name
    function startEdit(device: any) {
        editingDeviceId = device.id;
        editingDeviceName = device.device_name || '';
    }

    // Cancel editing
    function cancelEdit() {
        editingDeviceId = null;
        editingDeviceName = '';
    }

    // Save renamed device
    async function saveRename(deviceId: string) {
        if (!editingDeviceName.trim()) {
            error = $text('settings.developers_devices_rename_empty_error');
            return;
        }

        try {
            processingDeviceId = deviceId;
            error = '';
            
            // Encrypt device name client-side using master key before sending to server
            const encryptedDeviceName = await encryptWithMasterKey(editingDeviceName.trim());
            if (!encryptedDeviceName) {
                throw new Error('Failed to encrypt device name');
            }

            const response = await fetch(getApiEndpoint(`/v1/settings/api-key-devices/${deviceId}/rename`), {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    encrypted_device_name: encryptedDeviceName
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to rename device');
            }

            // Reload devices after rename
            await loadDevices();
            editingDeviceId = null;
            editingDeviceName = '';
        } catch (err: any) {
            console.error('Error renaming device:', err);
            error = err.message || 'Failed to rename device';
        } finally {
            processingDeviceId = null;
        }
    }
</script>

<div class="devices-container" data-testid="devices-container">
    <h2 class="page-title">{$text('common.devices')}</h2>
    <p class="page-description">{$text('settings.developers_devices_description')}</p>

    {#if error}
        <div class="error-message">{error}</div>
    {/if}

    {#if loading}
        <div class="loading">{$text('settings.developers_devices_loading')}</div>
    {:else if devices.length === 0}
        <div class="empty-state">
            <p>{$text('settings.developers_devices_no_devices')}</p>
        </div>
    {:else}
        <div class="devices-list">
            {#each devices as device (device.id)}
                <div class="device-card" class:pending={!device.approved_at}>
                    <div class="device-header">
                        <div class="device-info">
                            {#if editingDeviceId === device.id}
                                <!-- Edit mode: show input field -->
                                <div class="device-name-edit">
                                    <SettingsInput
                                        type="text"
                                        bind:value={editingDeviceName}
                                        placeholder={$text('settings.developers_devices_name_placeholder')}
                                        disabled={processingDeviceId === device.id}
                                    />
                                    <div class="device-name-actions">
                                        <button
                                            class="btn btn-save"
                                            onclick={() => saveRename(device.id)}
                                            disabled={processingDeviceId === device.id}
                                        >
                                            {processingDeviceId === device.id ? $text('common.processing') : $text('common.save')}
                                        </button>
                                        <button
                                            class="btn btn-cancel"
                                            onclick={() => cancelEdit()}
                                            disabled={processingDeviceId === device.id}
                                        >
                                            {$text('common.cancel')}
                                        </button>
                                    </div>
                                </div>
                            {:else}
                                <!-- Display mode: show device name or location -->
                                <h3 class="device-location">
                                    {device.device_name || device.city || device.region || device.country_code || 'Unknown Location'}
                                    {#if device.country_code && !device.device_name}
                                        <span class="country-code">({device.country_code})</span>
                                    {/if}
                                </h3>
                            {/if}
                            <p class="device-ip">{device.anonymized_ip || 'Unknown IP'}</p>
                            <p class="device-type">{getAccessTypeLabel(device.access_type || 'rest_api')}</p>
                        </div>
                        <div class="device-status">
                            {#if device.approved_at}
                                <span class="status-badge approved">{$text('settings.developers_devices_status_approved')}</span>
                            {:else}
                                <span class="status-badge pending">{$text('settings.developers_devices_status_pending')}</span>
                            {/if}
                        </div>
                    </div>

                    <div class="device-details">
                        <div class="detail-row">
                            <span class="detail-label">{$text('settings.developers_devices_first_access')}:</span>
                            <span class="detail-value">{formatDate(device.first_access_at)}</span>
                        </div>
                        <div class="detail-row">
                            <span class="detail-label">{$text('settings.developers_devices_last_access')}:</span>
                            <span class="detail-value">{formatDate(device.last_access_at)}</span>
                        </div>
                    </div>

                    <div class="device-actions">
                        {#if editingDeviceId !== device.id}
                            <button
                                class="btn btn-rename"
                                onclick={() => startEdit(device)}
                                disabled={processingDeviceId === device.id}
                            >
                                {$text('settings.developers_devices_rename')}
                            </button>
                            {#if !device.approved_at}
                                <button
                                    class="btn btn-approve"
                                    data-testid="device-approve-button"
                                    onclick={() => approveDevice(device.id)}
                                    disabled={processingDeviceId === device.id}
                                >
                                    {processingDeviceId === device.id ? $text('common.processing') : $text('settings.developers_devices_approve')}
                                </button>
                            {/if}
                            <button
                                class="btn btn-revoke"
                                onclick={() => revokeDevice(device.id)}
                                disabled={processingDeviceId === device.id}
                            >
                                {processingDeviceId === device.id ? $text('common.processing') : $text('settings.developers_devices_revoke')}
                            </button>
                        {/if}
                    </div>
                </div>
            {/each}
        </div>
    {/if}
</div>

<style>
    .devices-container {
        width: 100%;
        padding: var(--spacing-10);
        max-width: 800px;
        margin: 0 auto;
    }

    .page-title {
        font-size: var(--font-size-h2-mobile);
        font-weight: 600;
        margin-bottom: var(--spacing-4);
        color: var(--color-grey-100);
    }

    .page-description {
        font-size: var(--font-size-small);
        color: var(--color-grey-60);
        margin-bottom: var(--spacing-12);
    }

    .error-message {
        background: rgba(223, 27, 65, 0.1);
        color: #df1b41;
        padding: var(--spacing-6);
        border-radius: var(--radius-3);
        font-size: var(--font-size-xs);
        border: 1px solid rgba(223, 27, 65, 0.3);
        margin-bottom: var(--spacing-8);
    }

    .loading, .empty-state {
        text-align: center;
        padding: var(--spacing-20) var(--spacing-10);
        color: var(--color-grey-60);
    }

    .devices-list {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-8);
    }

    .device-card {
        background: var(--color-grey-10);
        border-radius: var(--radius-5);
        padding: var(--spacing-10);
        border: 1px solid var(--color-grey-20);
        transition: all var(--duration-normal);
    }

    .device-card.pending {
        border-color: #ffa500;
        background: rgba(255, 165, 0, 0.05);
    }

    .device-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: var(--spacing-8);
    }

    .device-info {
        flex: 1;
    }

    .device-location {
        font-size: var(--font-size-h3-mobile);
        font-weight: 600;
        margin: 0 0 4px 0;
        color: var(--color-grey-100);
    }

    .country-code {
        font-size: var(--font-size-small);
        font-weight: 400;
        color: var(--color-grey-60);
    }

    .device-ip {
        font-size: var(--font-size-small);
        color: var(--color-grey-60);
        margin: 4px 0;
    }

    .device-type {
        font-size: var(--font-size-xxs);
        color: var(--color-grey-50);
        margin: 4px 0 0 0;
    }

    .device-status {
        margin-left: var(--spacing-8);
    }

    .status-badge {
        display: inline-block;
        padding: var(--spacing-2) var(--spacing-6);
        border-radius: var(--radius-5);
        font-size: var(--font-size-xxs);
        font-weight: 500;
    }

    .status-badge.approved {
        background: rgba(34, 197, 94, 0.1);
        color: #22c55e;
    }

    .status-badge.pending {
        background: rgba(255, 165, 0, 0.1);
        color: #ffa500;
    }

    .device-details {
        margin-bottom: var(--spacing-8);
        padding-top: var(--spacing-8);
        border-top: 1px solid var(--color-grey-20);
    }

    .detail-row {
        display: flex;
        justify-content: space-between;
        margin-bottom: var(--spacing-4);
        font-size: var(--font-size-xs);
    }

    .detail-label {
        color: var(--color-grey-60);
    }

    .detail-value {
        color: var(--color-grey-100);
        font-weight: 500;
    }

    .device-actions {
        display: flex;
        gap: var(--spacing-4);
        padding-top: var(--spacing-8);
        border-top: 1px solid var(--color-grey-20);
    }

    .btn {
        padding: var(--spacing-4) var(--spacing-8);
        border-radius: var(--radius-3);
        font-size: var(--font-size-small);
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition: all var(--duration-normal);
    }

    .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .btn-approve {
        background: #22c55e;
        color: white;
    }

    .btn-approve:hover:not(:disabled) {
        background: #16a34a;
    }

    .btn-revoke {
        background: rgba(223, 27, 65, 0.1);
        color: #df1b41;
    }

    .btn-revoke:hover:not(:disabled) {
        background: rgba(223, 27, 65, 0.2);
    }

    .btn-rename {
        background: rgba(59, 130, 246, 0.1);
        color: #3b82f6;
    }

    .btn-rename:hover:not(:disabled) {
        background: rgba(59, 130, 246, 0.2);
    }

    .btn-save {
        background: #22c55e;
        color: white;
    }

    .btn-save:hover:not(:disabled) {
        background: #16a34a;
    }

    .btn-cancel {
        background: var(--color-grey-20);
        color: var(--color-grey-100);
    }

    .btn-cancel:hover:not(:disabled) {
        background: var(--color-grey-30);
    }

    .device-name-edit {
        width: 100%;
        margin-bottom: var(--spacing-4);
    }

    .device-name-actions {
        display: flex;
        gap: var(--spacing-4);
    }

    @media (max-width: 768px) {
        .devices-container {
            padding: var(--spacing-8);
        }

        .device-header {
            flex-direction: column;
        }

        .device-status {
            margin-left: 0;
            margin-top: var(--spacing-6);
        }

        .device-actions {
            flex-direction: column;
        }

        .btn {
            width: 100%;
        }
    }
</style>
