<!--
    SettingsDevices — API key device approval and revocation UI.

    Uses only canonical settings elements: list rows for devices and a detail
    panel for approve/reject/revoke/rename actions. Device metadata stays
    zero-knowledge; custom names are encrypted before saving.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint } from '../../../config/api';
    import { encryptWithMasterKey, decryptWithMasterKey } from '../../../services/cryptoService';
    import {
        SettingsBadge,
        SettingsButton,
        SettingsButtonGroup,
        SettingsCard,
        SettingsDetailRow,
        SettingsInfoBox,
        SettingsInput,
        SettingsItem,
        SettingsLoadingState,
        SettingsPageContainer,
        SettingsPageHeader,
    } from '../elements';

    type ApiKeyDevice = {
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
        device_name?: string | null;
    };

    let devices = $state<ApiKeyDevice[]>([]);
    let loading = $state(true);
    let error = $state<string>('');
    let processingDeviceId = $state<string | null>(null);
    let editingDeviceId = $state<string | null>(null);
    let editingDeviceName = $state('');
    let selectedDeviceId = $state<string | null>(null);

    let selectedDevice = $derived(
        selectedDeviceId ? devices.find((device) => device.id === selectedDeviceId) : null
    );

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
                credentials: 'include'
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to load devices');
            }

            const data = await response.json();
            const rawDevices = data.devices || [];
            const decryptedDevices = [];

            for (const device of rawDevices) {
                let deviceName = null;
                if (device.encrypted_device_name) {
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
            if (selectedDeviceId && !devices.some((device) => device.id === selectedDeviceId)) {
                selectedDeviceId = null;
            }
        } catch (err: unknown) {
            console.error('Error loading devices:', err);
            error = err instanceof Error ? err.message : 'Failed to load devices';
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

            await loadDevices();
        } catch (err: unknown) {
            console.error('Error approving device:', err);
            error = err instanceof Error ? err.message : 'Failed to approve device';
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

            selectedDeviceId = null;
            await loadDevices();
        } catch (err: unknown) {
            console.error('Error revoking device:', err);
            error = err instanceof Error ? err.message : 'Failed to revoke device';
        } finally {
            processingDeviceId = null;
        }
    }

    function formatDate(dateString: string | null | undefined): string {
        if (!dateString) return $text('settings.api_keys.unknown');
        try {
            const date = new Date(dateString);
            return date.toLocaleString();
        } catch {
            return dateString;
        }
    }

    function getAccessTypeLabel(accessType: string): string {
        const normalizedAccessType = accessType === 'npm' || accessType === 'pip' ? 'sdk' : accessType;
        const labels: Record<string, string> = {
            'rest_api': $text('settings.developers_devices_access_type_rest_api'),
            'cli': $text('settings.developers_devices_access_type_cli'),
            'sdk': $text('settings.developers_devices_access_type_sdk')
        };
        return labels[normalizedAccessType] || accessType;
    }

    function getDeviceTitle(device: ApiKeyDevice): string {
        return device.device_name || device.city || device.region || device.country_code || $text('settings.api_keys.unknown');
    }

    function getDeviceSubtitle(device: ApiKeyDevice): string {
        const status = device.approved_at
            ? $text('settings.developers_devices_status_approved')
            : $text('settings.developers_devices_status_pending');
        return `${getAccessTypeLabel(device.access_type || 'rest_api')} · ${device.anonymized_ip || $text('settings.api_keys.unknown')} · ${status}`;
    }

    function startEdit(device: ApiKeyDevice) {
        editingDeviceId = device.id;
        editingDeviceName = device.device_name || getDeviceTitle(device);
    }

    function cancelEdit() {
        editingDeviceId = null;
        editingDeviceName = '';
    }

    async function saveRename(deviceId: string) {
        if (!editingDeviceName.trim()) {
            error = $text('settings.developers_devices_rename_empty_error');
            return;
        }

        try {
            processingDeviceId = deviceId;
            error = '';
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

            await loadDevices();
            editingDeviceId = null;
            editingDeviceName = '';
        } catch (err: unknown) {
            console.error('Error renaming device:', err);
            error = err instanceof Error ? err.message : 'Failed to rename device';
        } finally {
            processingDeviceId = null;
        }
    }
</script>

<SettingsPageContainer>
    {#if selectedDevice}
        <SettingsButton
            variant="ghost"
            size="sm"
            dataTestid="device-detail-back-button"
            onClick={() => selectedDeviceId = null}
        >
            {$text('common.back')}
        </SettingsButton>
        <SettingsPageHeader
            title={getDeviceTitle(selectedDevice)}
            description={getDeviceSubtitle(selectedDevice)}
        />
    {:else}
        <SettingsPageHeader
            title={$text('common.devices')}
            description={$text('settings.developers_devices_description')}
        />
    {/if}

    {#if error}
        <SettingsInfoBox type="error">
            <p>{error}</p>
        </SettingsInfoBox>
    {/if}

    {#if loading}
        <SettingsLoadingState variant="spinner" text={$text('settings.developers_devices_loading')} />
    {:else if selectedDevice}
        <SettingsCard>
            <SettingsBadge
                variant={selectedDevice.approved_at ? 'success' : 'warning'}
                text={selectedDevice.approved_at
                    ? $text('settings.developers_devices_status_approved')
                    : $text('settings.developers_devices_status_pending')}
            />
            <SettingsDetailRow label={$text('common.status')} value={selectedDevice.approved_at ? $text('settings.developers_devices_status_approved') : $text('settings.developers_devices_status_pending')} />
            <SettingsDetailRow label={$text('settings.developers_devices_ip_address')} value={selectedDevice.anonymized_ip || $text('settings.api_keys.unknown')} />
            <SettingsDetailRow label={$text('settings.developers_devices_access_type')} value={getAccessTypeLabel(selectedDevice.access_type || 'rest_api')} />
            <SettingsDetailRow label={$text('settings.developers_devices_api_key')} value={selectedDevice.api_key_id} />
            <SettingsDetailRow label={$text('settings.developers_devices_first_access')} value={formatDate(selectedDevice.first_access_at)} />
            <SettingsDetailRow label={$text('settings.developers_devices_last_access')} value={formatDate(selectedDevice.last_access_at)} />
        </SettingsCard>

        {#if editingDeviceId === selectedDevice.id}
            <SettingsInput
                type="text"
                bind:value={editingDeviceName}
                placeholder={$text('settings.developers_devices_name_placeholder')}
                disabled={processingDeviceId === selectedDevice.id}
                dataTestid="device-rename-input"
            />
            <SettingsButtonGroup align="space-between">
                <SettingsButton
                    variant="secondary"
                    dataTestid="device-rename-cancel-button"
                    onClick={cancelEdit}
                    disabled={processingDeviceId === selectedDevice.id}
                >
                    {$text('common.cancel')}
                </SettingsButton>
                <SettingsButton
                    variant="primary"
                    dataTestid="device-rename-save-button"
                    onClick={() => saveRename(selectedDevice.id)}
                    loading={processingDeviceId === selectedDevice.id}
                >
                    {$text('common.save')}
                </SettingsButton>
            </SettingsButtonGroup>
        {:else}
            <SettingsButtonGroup align="space-between">
                <SettingsButton
                    variant="secondary"
                    dataTestid="device-rename-button"
                    onClick={() => startEdit(selectedDevice)}
                    disabled={processingDeviceId === selectedDevice.id}
                >
                    {$text('settings.developers_devices_rename')}
                </SettingsButton>
                {#if !selectedDevice.approved_at}
                    <SettingsButton
                        variant="primary"
                        dataTestid="device-approve-button"
                        onClick={() => approveDevice(selectedDevice.id)}
                        loading={processingDeviceId === selectedDevice.id}
                    >
                        {$text('settings.developers_devices_approve')}
                    </SettingsButton>
                {/if}
                <SettingsButton
                    variant="danger"
                    dataTestid="device-revoke-button"
                    onClick={() => revokeDevice(selectedDevice.id)}
                    loading={processingDeviceId === selectedDevice.id}
                >
                    {selectedDevice.approved_at ? $text('settings.developers_devices_revoke') : $text('settings.developers_devices_reject')}
                </SettingsButton>
            </SettingsButtonGroup>
        {/if}
    {:else if devices.length === 0}
        <SettingsLoadingState
            variant="empty"
            text={$text('settings.developers_devices_no_devices')}
        />
    {:else}
        {#each devices as device (device.id)}
            <SettingsItem
                type="submenu"
                icon="subsetting_icon devices"
                title={getDeviceTitle(device)}
                subtitleTop={getDeviceSubtitle(device)}
                onClick={() => selectedDeviceId = device.id}
                data-testid="device-row"
            />
        {/each}
    {/if}
</SettingsPageContainer>
