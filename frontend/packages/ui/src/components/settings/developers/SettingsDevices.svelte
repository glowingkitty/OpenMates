<!--
SettingsDevices - Manage API key devices (approve/revoke devices that use API keys)
-->

<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint } from '../../../config/api';

    const dispatch = createEventDispatcher();

    // State using Svelte 5 $state() runes
    let devices = $state<any[]>([]);
    let loading = $state(true);
    let error = $state<string>('');
    let processingDeviceId = $state<string | null>(null);

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
            devices = data.devices || [];
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
        if (!confirm($text('settings.developers_devices_confirm_revoke.text'))) {
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
            'rest_api': $text('settings.developers_devices_access_type_rest_api.text'),
            'cli': $text('settings.developers_devices_access_type_cli.text'),
            'pip': $text('settings.developers_devices_access_type_pip.text'),
            'npm': $text('settings.developers_devices_access_type_npm.text')
        };
        return labels[accessType] || accessType;
    }
</script>

<div class="devices-container">
    <h2 class="page-title">{$text('settings.developers_devices_text.text')}</h2>
    <p class="page-description">{$text('settings.developers_devices_description.text')}</p>

    {#if error}
        <div class="error-message">{error}</div>
    {/if}

    {#if loading}
        <div class="loading">{$text('settings.developers_devices_loading.text')}</div>
    {:else if devices.length === 0}
        <div class="empty-state">
            <p>{$text('settings.developers_devices_no_devices.text')}</p>
        </div>
    {:else}
        <div class="devices-list">
            {#each devices as device (device.id)}
                <div class="device-card" class:pending={!device.approved_at}>
                    <div class="device-header">
                        <div class="device-info">
                            <h3 class="device-location">
                                {device.city || device.region || device.country_code || 'Unknown Location'}
                                {#if device.country_code}
                                    <span class="country-code">({device.country_code})</span>
                                {/if}
                            </h3>
                            <p class="device-ip">{device.anonymized_ip || 'Unknown IP'}</p>
                            <p class="device-type">{getAccessTypeLabel(device.access_type || 'rest_api')}</p>
                        </div>
                        <div class="device-status">
                            {#if device.approved_at}
                                <span class="status-badge approved">{$text('settings.developers_devices_status_approved.text')}</span>
                            {:else}
                                <span class="status-badge pending">{$text('settings.developers_devices_status_pending.text')}</span>
                            {/if}
                        </div>
                    </div>

                    <div class="device-details">
                        <div class="detail-row">
                            <span class="detail-label">{$text('settings.developers_devices_first_access.text')}:</span>
                            <span class="detail-value">{formatDate(device.first_access_at)}</span>
                        </div>
                        <div class="detail-row">
                            <span class="detail-label">{$text('settings.developers_devices_last_access.text')}:</span>
                            <span class="detail-value">{formatDate(device.last_access_at)}</span>
                        </div>
                    </div>

                    <div class="device-actions">
                        {#if !device.approved_at}
                            <button
                                class="btn btn-approve"
                                onclick={() => approveDevice(device.id)}
                                disabled={processingDeviceId === device.id}
                            >
                                {processingDeviceId === device.id ? $text('settings.developers_devices_processing.text') : $text('settings.developers_devices_approve.text')}
                            </button>
                        {/if}
                        <button
                            class="btn btn-revoke"
                            onclick={() => revokeDevice(device.id)}
                            disabled={processingDeviceId === device.id}
                        >
                            {processingDeviceId === device.id ? $text('settings.developers_devices_processing.text') : $text('settings.developers_devices_revoke.text')}
                        </button>
                    </div>
                </div>
            {/each}
        </div>
    {/if}
</div>

<style>
    .devices-container {
        width: 100%;
        padding: 20px;
        max-width: 800px;
        margin: 0 auto;
    }

    .page-title {
        font-size: 24px;
        font-weight: 600;
        margin-bottom: 8px;
        color: var(--color-grey-100);
    }

    .page-description {
        font-size: 14px;
        color: var(--color-grey-60);
        margin-bottom: 24px;
    }

    .error-message {
        background: rgba(223, 27, 65, 0.1);
        color: #df1b41;
        padding: 12px;
        border-radius: 8px;
        font-size: 13px;
        border: 1px solid rgba(223, 27, 65, 0.3);
        margin-bottom: 16px;
    }

    .loading, .empty-state {
        text-align: center;
        padding: 40px 20px;
        color: var(--color-grey-60);
    }

    .devices-list {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .device-card {
        background: var(--color-grey-10);
        border-radius: 12px;
        padding: 20px;
        border: 1px solid var(--color-grey-20);
        transition: all 0.2s;
    }

    .device-card.pending {
        border-color: #ffa500;
        background: rgba(255, 165, 0, 0.05);
    }

    .device-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 16px;
    }

    .device-info {
        flex: 1;
    }

    .device-location {
        font-size: 18px;
        font-weight: 600;
        margin: 0 0 4px 0;
        color: var(--color-grey-100);
    }

    .country-code {
        font-size: 14px;
        font-weight: 400;
        color: var(--color-grey-60);
    }

    .device-ip {
        font-size: 14px;
        color: var(--color-grey-60);
        margin: 4px 0;
    }

    .device-type {
        font-size: 12px;
        color: var(--color-grey-50);
        margin: 4px 0 0 0;
    }

    .device-status {
        margin-left: 16px;
    }

    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 12px;
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
        margin-bottom: 16px;
        padding-top: 16px;
        border-top: 1px solid var(--color-grey-20);
    }

    .detail-row {
        display: flex;
        justify-content: space-between;
        margin-bottom: 8px;
        font-size: 13px;
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
        gap: 8px;
        padding-top: 16px;
        border-top: 1px solid var(--color-grey-20);
    }

    .btn {
        padding: 8px 16px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition: all 0.2s;
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

    @media (max-width: 768px) {
        .devices-container {
            padding: 16px;
        }

        .device-header {
            flex-direction: column;
        }

        .device-status {
            margin-left: 0;
            margin-top: 12px;
        }

        .device-actions {
            flex-direction: column;
        }

        .btn {
            width: 100%;
        }
    }
</style>
