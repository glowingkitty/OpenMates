<!--
    Settings Timezone Component - Allows users to view and change their timezone
    Timezone is auto-detected on login but can be manually changed here.
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../../SettingsItem.svelte';
    import { getApiUrl, apiEndpoints } from '../../../config/api';
    import { userProfile, updateProfile } from '../../../stores/userProfile';

    // Common timezones grouped by region for easier selection
    const TIMEZONE_GROUPS = [
        {
            region: 'Americas',
            timezones: [
                { id: 'America/New_York', label: 'New York (EST/EDT)' },
                { id: 'America/Chicago', label: 'Chicago (CST/CDT)' },
                { id: 'America/Denver', label: 'Denver (MST/MDT)' },
                { id: 'America/Los_Angeles', label: 'Los Angeles (PST/PDT)' },
                { id: 'America/Anchorage', label: 'Anchorage (AKST/AKDT)' },
                { id: 'America/Toronto', label: 'Toronto (EST/EDT)' },
                { id: 'America/Vancouver', label: 'Vancouver (PST/PDT)' },
                { id: 'America/Mexico_City', label: 'Mexico City (CST/CDT)' },
                { id: 'America/Sao_Paulo', label: 'Sao Paulo (BRT)' },
                { id: 'America/Buenos_Aires', label: 'Buenos Aires (ART)' },
            ]
        },
        {
            region: 'Europe',
            timezones: [
                { id: 'Europe/London', label: 'London (GMT/BST)' },
                { id: 'Europe/Paris', label: 'Paris (CET/CEST)' },
                { id: 'Europe/Berlin', label: 'Berlin (CET/CEST)' },
                { id: 'Europe/Amsterdam', label: 'Amsterdam (CET/CEST)' },
                { id: 'Europe/Brussels', label: 'Brussels (CET/CEST)' },
                { id: 'Europe/Vienna', label: 'Vienna (CET/CEST)' },
                { id: 'Europe/Zurich', label: 'Zurich (CET/CEST)' },
                { id: 'Europe/Madrid', label: 'Madrid (CET/CEST)' },
                { id: 'Europe/Rome', label: 'Rome (CET/CEST)' },
                { id: 'Europe/Stockholm', label: 'Stockholm (CET/CEST)' },
                { id: 'Europe/Warsaw', label: 'Warsaw (CET/CEST)' },
                { id: 'Europe/Prague', label: 'Prague (CET/CEST)' },
                { id: 'Europe/Athens', label: 'Athens (EET/EEST)' },
                { id: 'Europe/Helsinki', label: 'Helsinki (EET/EEST)' },
                { id: 'Europe/Moscow', label: 'Moscow (MSK)' },
            ]
        },
        {
            region: 'Asia',
            timezones: [
                { id: 'Asia/Dubai', label: 'Dubai (GST)' },
                { id: 'Asia/Kolkata', label: 'India (IST)' },
                { id: 'Asia/Bangkok', label: 'Bangkok (ICT)' },
                { id: 'Asia/Singapore', label: 'Singapore (SGT)' },
                { id: 'Asia/Hong_Kong', label: 'Hong Kong (HKT)' },
                { id: 'Asia/Shanghai', label: 'Shanghai (CST)' },
                { id: 'Asia/Tokyo', label: 'Tokyo (JST)' },
                { id: 'Asia/Seoul', label: 'Seoul (KST)' },
                { id: 'Asia/Jakarta', label: 'Jakarta (WIB)' },
            ]
        },
        {
            region: 'Pacific',
            timezones: [
                { id: 'Pacific/Auckland', label: 'Auckland (NZST/NZDT)' },
                { id: 'Australia/Sydney', label: 'Sydney (AEST/AEDT)' },
                { id: 'Australia/Melbourne', label: 'Melbourne (AEST/AEDT)' },
                { id: 'Australia/Brisbane', label: 'Brisbane (AEST)' },
                { id: 'Australia/Perth', label: 'Perth (AWST)' },
                { id: 'Pacific/Honolulu', label: 'Honolulu (HST)' },
            ]
        },
        {
            region: 'Africa',
            timezones: [
                { id: 'Africa/Cairo', label: 'Cairo (EET)' },
                { id: 'Africa/Johannesburg', label: 'Johannesburg (SAST)' },
                { id: 'Africa/Lagos', label: 'Lagos (WAT)' },
                { id: 'Africa/Nairobi', label: 'Nairobi (EAT)' },
            ]
        }
    ];

    // Current timezone from user profile or browser
    let currentTimezone = $state<string>('');
    let browserTimezone = $state<string>('');
    let isLoading = $state(true);
    let isSaving = $state(false);
    let errorMessage = $state<string | null>(null);
    let successMessage = $state<string | null>(null);

    // Get display label for a timezone ID
    function getTimezoneLabel(timezoneId: string): string {
        for (const group of TIMEZONE_GROUPS) {
            const tz = group.timezones.find(t => t.id === timezoneId);
            if (tz) return tz.label;
        }
        // Fallback: just show the ID in a readable format
        return timezoneId.replace(/_/g, ' ').replace(/\//g, ' / ');
    }

    // Check if timezone is in our predefined list
    function isKnownTimezone(timezoneId: string): boolean {
        return TIMEZONE_GROUPS.some(group => 
            group.timezones.some(tz => tz.id === timezoneId)
        );
    }

    // Handle timezone selection
    async function handleTimezoneChange(newTimezone: string) {
        if (newTimezone === currentTimezone || isSaving) return;

        isSaving = true;
        errorMessage = null;
        successMessage = null;

        try {
            const response = await fetch(getApiUrl() + apiEndpoints.settings.user.timezone, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                body: JSON.stringify({ timezone: newTimezone }),
                credentials: 'include'
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || 'Failed to update timezone');
            }

            currentTimezone = newTimezone;
            
            // Update user profile store
            updateProfile({ timezone: newTimezone });
            
            successMessage = $text('settings.account.timezone_saved');
            
            // Clear success message after 3 seconds
            setTimeout(() => {
                successMessage = null;
            }, 3000);

        } catch (error) {
            console.error('[SettingsTimezone] Error saving timezone:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to save timezone';
        } finally {
            isSaving = false;
        }
    }

    // Use browser's detected timezone
    async function useBrowserTimezone() {
        if (browserTimezone && browserTimezone !== currentTimezone) {
            await handleTimezoneChange(browserTimezone);
        }
    }

    onMount(() => {
        // Get browser's timezone
        browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        
        // Get current timezone from user profile
        currentTimezone = $userProfile.timezone || browserTimezone;
        
        isLoading = false;
    });
</script>

<div class="settings-timezone">
    {#if isLoading}
        <div class="loading">{$text('settings.account.timezone_loading')}</div>
    {:else}
        <!-- Current timezone display -->
        <div class="current-timezone-section">
            <SettingsItem
                type="nested"
                icon="clock"
                title={$text('settings.account.timezone_current')}
                subtitleTop={getTimezoneLabel(currentTimezone)}
            />
            
            {#if browserTimezone && browserTimezone !== currentTimezone}
                <div class="browser-timezone-hint">
                    <button 
                        class="use-browser-btn"
                        onclick={useBrowserTimezone}
                        disabled={isSaving}
                    >
                        {$text('settings.account.timezone_use_browser')} ({getTimezoneLabel(browserTimezone)})
                    </button>
                </div>
            {/if}
        </div>

        <!-- Messages -->
        {#if errorMessage}
            <div class="message error">{errorMessage}</div>
        {/if}
        {#if successMessage}
            <div class="message success">{successMessage}</div>
        {/if}

        <!-- Timezone selection by region -->
        {#each TIMEZONE_GROUPS as group}
            <div class="timezone-group">
                <h3 class="region-header">{group.region}</h3>
                <div class="timezone-list">
                    {#each group.timezones as tz}
                        <SettingsItem 
                            type="quickaction"
                            icon="clock"
                            title={tz.label}
                            hasToggle={true}
                            checked={currentTimezone === tz.id}
                            onClick={() => handleTimezoneChange(tz.id)}
                            disabled={isSaving}
                        />
                    {/each}
                </div>
            </div>
        {/each}

        <!-- Show current timezone if not in predefined list -->
        {#if currentTimezone && !isKnownTimezone(currentTimezone)}
            <div class="timezone-group">
                <h3 class="region-header">{$text('settings.account.timezone_other')}</h3>
                <div class="timezone-list">
                    <SettingsItem 
                        type="quickaction"
                        icon="clock"
                        title={getTimezoneLabel(currentTimezone)}
                        hasToggle={true}
                        checked={true}
                        onClick={() => {}}
                    />
                </div>
            </div>
        {/if}

        <div class="info-box">
            <p>{$text('settings.account.timezone_info')}</p>
        </div>
    {/if}
</div>

<style>
    .settings-timezone {
        padding: 0;
    }

    .loading {
        padding: 1.5rem;
        text-align: center;
        color: var(--color-text-secondary);
    }

    .current-timezone-section {
        margin-bottom: 1rem;
    }

    .browser-timezone-hint {
        padding: 0 1rem 1rem;
    }

    .use-browser-btn {
        width: 100%;
        padding: 0.75rem 1rem;
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: 8px;
        color: var(--color-primary);
        font-size: 0.9rem;
        cursor: pointer;
        transition: background-color 0.2s ease;
    }

    .use-browser-btn:hover:not(:disabled) {
        background: var(--color-background-tertiary);
    }

    .use-browser-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .message {
        margin: 0.5rem 1rem;
        padding: 0.75rem 1rem;
        border-radius: 8px;
        font-size: 0.9rem;
    }

    .message.error {
        background: var(--color-error-background, rgba(255, 0, 0, 0.1));
        color: var(--color-error);
        border: 1px solid var(--color-error);
    }

    .message.success {
        background: var(--color-success-background, rgba(0, 255, 0, 0.1));
        color: var(--color-success);
        border: 1px solid var(--color-success);
    }

    .timezone-group {
        margin-bottom: 1.5rem;
    }

    .region-header {
        padding: 0.5rem 1rem;
        margin: 0;
        font-size: 0.85rem;
        font-weight: 600;
        color: var(--color-text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .timezone-list {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .info-box {
        margin: 1.5rem 1rem;
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
