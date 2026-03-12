<!--
SettingsSessions - Active Sessions management page
Shows all connected devices/sessions, allows removal of individual sessions,
logout all other devices, and logout all devices (nuclear option).
Architecture: docs/architecture/device-sessions.md
-->

<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint } from '../../../config/api';
    import { decryptWithMasterKey } from '../../../services/cryptoService';
    import { pendingPairToken } from '../../../stores/pairSessionStore';

    const dispatch = createEventDispatcher();

    // ========================================================================
    // TYPES
    // ========================================================================

    interface SessionMeta {
        device_name: string;
        ip_truncated: string;
        country_code: string | null;
        city: string | null;
    }

    interface SessionItem {
        session_id: string;
        is_current: boolean;
        created_at: number;
        stay_logged_in: boolean;
        // Decrypted / plaintext fields for display
        device_name: string;
        ip_truncated: string;
        country_code: string | null;
        city: string | null;
        // Whether metadata came from encrypted blob
        has_encrypted_meta: boolean;
    }

    // ========================================================================
    // STATE
    // ========================================================================

    let sessions = $state<SessionItem[]>([]);
    let loading = $state(true);
    let error = $state('');
    let processingSessionId = $state<string | null>(null);
    let processingAll = $state(false);
    let addDeviceInput = $state('');
    let addDeviceError = $state('');

    // ========================================================================
    // LIFECYCLE
    // ========================================================================

    onMount(() => {
        loadSessions();
    });

    // ========================================================================
    // HELPERS
    // ========================================================================

    /**
     * Convert a 2-letter ISO country code to a flag emoji.
     * e.g. "DE" -> "🇩🇪", "US" -> "🇺🇸"
     */
    function countryCodeToFlag(code: string | null): string {
        if (!code || code.length !== 2) return '';
        const upper = code.toUpperCase();
        const codePoints = [...upper].map(c => 0x1F1E6 - 65 + c.charCodeAt(0));
        return String.fromCodePoint(...codePoints);
    }

    /**
     * Map ISO country code to country name (English).
     * Uses Intl.DisplayNames if available, falls back to code.
     */
    function countryName(code: string | null): string {
        if (!code || code.length !== 2) return '';
        try {
            const names = new Intl.DisplayNames(['en'], { type: 'region' });
            return names.of(code.toUpperCase()) || code;
        } catch {
            return code;
        }
    }

    /**
     * Format a Unix timestamp as a relative time string with absolute tooltip.
     */
    function formatRelativeTime(timestamp: number): string {
        if (!timestamp) return '-';
        const now = Date.now() / 1000;
        const diff = now - timestamp;

        if (diff < 60) return $text('settings.sessions.just_now');
        if (diff < 3600) {
            const mins = Math.floor(diff / 60);
            return mins === 1
                ? $text('settings.sessions.minute_ago')
                : $text('settings.sessions.minutes_ago').replace('{n}', String(mins));
        }
        if (diff < 86400) {
            const hours = Math.floor(diff / 3600);
            return hours === 1
                ? $text('settings.sessions.hour_ago')
                : $text('settings.sessions.hours_ago').replace('{n}', String(hours));
        }
        const days = Math.floor(diff / 86400);
        return days === 1
            ? $text('settings.sessions.day_ago')
            : $text('settings.sessions.days_ago').replace('{n}', String(days));
    }

    function formatAbsoluteTime(timestamp: number): string {
        if (!timestamp) return '';
        try {
            return new Date(timestamp * 1000).toLocaleString();
        } catch {
            return '';
        }
    }

    // ========================================================================
    // DATA FETCHING
    // ========================================================================

    async function loadSessions() {
        try {
            loading = true;
            error = '';

            const response = await fetch(getApiEndpoint('/v1/auth/sessions'), {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(errData.detail || 'Failed to load sessions');
            }

            const data = await response.json();
            const rawSessions = data.sessions || [];

            // Decrypt encrypted metadata for each session
            const decrypted: SessionItem[] = [];
            for (const s of rawSessions) {
                let deviceName = s.device_name || $text('settings.sessions.unknown_device');
                let ipTruncated = s.ip_truncated || '';
                let countryCode = s.country_code || null;
                let city = s.city || null;
                let hasEncrypted = false;

                if (s.encrypted_meta) {
                    hasEncrypted = true;
                    try {
                        const decryptedJson = await decryptWithMasterKey(s.encrypted_meta);
                        if (decryptedJson) {
                            const meta: SessionMeta = JSON.parse(decryptedJson);
                            deviceName = meta.device_name || deviceName;
                            ipTruncated = meta.ip_truncated || ipTruncated;
                            countryCode = meta.country_code || countryCode;
                            city = meta.city || city;
                        }
                    } catch (e) {
                        console.warn('[SettingsSessions] Failed to decrypt session meta:', e);
                    }
                }

                decrypted.push({
                    session_id: s.session_id,
                    is_current: s.is_current,
                    created_at: s.created_at,
                    stay_logged_in: s.stay_logged_in,
                    device_name: deviceName,
                    ip_truncated: ipTruncated,
                    country_code: countryCode,
                    city: city,
                    has_encrypted_meta: hasEncrypted,
                });
            }

            sessions = decrypted;
        } catch (err: unknown) {
            console.error('[SettingsSessions] Error loading sessions:', err);
            error = (err instanceof Error ? err.message : undefined) || 'Failed to load sessions';
        } finally {
            loading = false;
        }
    }

    // ========================================================================
    // ACTIONS
    // ========================================================================

    async function revokeSession(sessionId: string) {
        if (!confirm($text('settings.sessions.confirm_remove'))) return;

        try {
            processingSessionId = sessionId;
            error = '';

            const response = await fetch(getApiEndpoint(`/v1/auth/sessions/${sessionId}`), {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(errData.detail || 'Failed to remove session');
            }

            await loadSessions();
        } catch (err: unknown) {
            console.error('[SettingsSessions] Error revoking session:', err);
            error = (err instanceof Error ? err.message : undefined) || 'Failed to remove session';
        } finally {
            processingSessionId = null;
        }
    }

    async function logoutAllOthers() {
        if (!confirm($text('settings.sessions.confirm_logout_others'))) return;

        try {
            processingAll = true;
            error = '';

            const response = await fetch(getApiEndpoint('/v1/auth/sessions/logout-others'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(errData.detail || 'Failed to logout other sessions');
            }

            await loadSessions();
        } catch (err: unknown) {
            console.error('[SettingsSessions] Error logging out others:', err);
            error = (err instanceof Error ? err.message : undefined) || 'Failed to logout other sessions';
        } finally {
            processingAll = false;
        }
    }

    async function logoutAllDevices() {
        if (!confirm($text('settings.sessions.confirm_logout_all'))) return;

        try {
            processingAll = true;
            error = '';

            const response = await fetch(getApiEndpoint('/v1/auth/sessions/logout-all-devices'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(errData.detail || 'Failed to logout all devices');
            }

            // Current session is also invalidated — trigger logout on this device
            dispatch('logout');
        } catch (err: unknown) {
            console.error('[SettingsSessions] Error logging out all devices:', err);
            error = (err instanceof Error ? err.message : undefined) || 'Failed to logout all devices';
        } finally {
            processingAll = false;
        }
    }

    // ========================================================================
    // NAVIGATION
    // ========================================================================

    function extractPairToken(rawInput: string): string | null {
        const trimmed = rawInput.trim();
        if (!trimmed) return null;

        const hashMatch = trimmed.match(/#pair=([A-Za-z0-9]{6})/i);
        if (hashMatch) {
            return hashMatch[1].toUpperCase();
        }

        const compact = trimmed.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
        if (compact.length === 6) {
            return compact;
        }

        return null;
    }

    function connectDevice() {
        addDeviceError = '';
        const token = extractPairToken(addDeviceInput);
        if (!token) {
            addDeviceError = 'Please enter a valid pair URL or 6-character code.';
            return;
        }

        pendingPairToken.set(token);
        dispatch('openSettings', {
            settingsPath: 'account/security/sessions/confirm-pair',
            direction: 'forward',
            icon: 'devices',
            title: $text('settings.sessions.pair_login_from_device_title'),
        });
    }

    // ========================================================================
    // DERIVED
    // ========================================================================

    let otherSessionCount = $derived(sessions.filter(s => !s.is_current).length);
</script>

<div class="sessions-container">
    <h2 class="page-title">{$text('settings.sessions.title')}</h2>
    <p class="page-description">{$text('settings.sessions.description')}</p>

    <div class="add-device-section">
        <h3 class="add-device-title">Add device</h3>
        <p class="add-device-description">Enter the pair URL or 6-character code from the new device.</p>
        <div class="add-device-row">
            <input
                type="text"
                class="add-device-input"
                placeholder="https://.../#pair=ABC123 or ABC123"
                value={addDeviceInput}
                oninput={(event) => {
                    addDeviceInput = (event.currentTarget as HTMLInputElement).value;
                    addDeviceError = '';
                }}
                onkeydown={(event) => {
                    if (event.key === 'Enter') connectDevice();
                }}
                autocomplete="off"
            />
            <button class="btn btn-connect" onclick={connectDevice}>Connect</button>
        </div>
        {#if addDeviceError}
            <p class="add-device-error">{addDeviceError}</p>
        {/if}
    </div>

    {#if error}
        <div class="error-message">{error}</div>
    {/if}

    {#if loading}
        <div class="loading">{$text('settings.sessions.loading')}</div>
    {:else if sessions.length === 0}
        <div class="empty-state">
            <p>{$text('settings.sessions.no_sessions')}</p>
        </div>
    {:else}
        <div class="sessions-list">
            {#each sessions as session (session.session_id)}
                <div class="session-card" class:current={session.is_current}>
                    <div class="session-header">
                        <div class="session-info">
                            <h3 class="session-device-name">
                                {#if session.country_code}
                                    <span class="flag">{countryCodeToFlag(session.country_code)}</span>
                                {/if}
                                {session.device_name}
                                {#if session.is_current}
                                    <span class="current-badge">{$text('settings.sessions.this_device')}</span>
                                {/if}
                            </h3>
                            <p class="session-location">
                                {#if session.country_code}
                                    {countryName(session.country_code)}
                                    {#if session.city}
                                        <span class="separator">&middot;</span> {session.city}
                                    {/if}
                                    {#if session.ip_truncated}
                                        <span class="separator">&middot;</span> {session.ip_truncated}
                                    {/if}
                                {:else if session.ip_truncated}
                                    {session.ip_truncated}
                                {:else}
                                    {$text('settings.sessions.unknown_location')}
                                {/if}
                            </p>
                        </div>
                    </div>

                    <div class="session-details">
                        <div class="detail-row">
                            <span class="detail-label">{$text('settings.sessions.logged_in')}:</span>
                            <span
                                class="detail-value"
                                title={formatAbsoluteTime(session.created_at)}
                            >
                                {formatRelativeTime(session.created_at)}
                            </span>
                        </div>
                        <div class="detail-row">
                            <span class="detail-label">{$text('settings.sessions.session_type')}:</span>
                            <span class="detail-value">
                                {session.stay_logged_in
                                    ? $text('settings.sessions.staying_logged_in')
                                    : $text('settings.sessions.session_only')}
                            </span>
                        </div>
                    </div>

                    {#if !session.is_current}
                        <div class="session-actions">
                            <button
                                class="btn btn-remove"
                                onclick={() => revokeSession(session.session_id)}
                                disabled={processingSessionId === session.session_id || processingAll}
                            >
                                {processingSessionId === session.session_id
                                    ? $text('settings.sessions.removing')
                                    : $text('settings.sessions.remove')}
                            </button>
                        </div>
                    {/if}
                </div>
            {/each}
        </div>

        <!-- Bulk actions -->
        {#if otherSessionCount > 0}
            <div class="bulk-actions">
                <button
                    class="btn btn-logout-others"
                    onclick={logoutAllOthers}
                    disabled={processingAll}
                >
                    {processingAll
                        ? $text('settings.sessions.processing')
                        : $text('settings.sessions.logout_all_others')}
                </button>
            </div>
        {/if}

        <div class="bulk-actions">
            <button
                class="btn btn-logout-all"
                onclick={logoutAllDevices}
                disabled={processingAll}
            >
                {processingAll
                    ? $text('settings.sessions.processing')
                    : $text('settings.sessions.logout_all_devices')}
            </button>
            <p class="destructive-hint">{$text('settings.sessions.logout_all_hint')}</p>
        </div>
    {/if}

</div>

<style>
    .sessions-container {
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

    .add-device-section {
        margin-bottom: 20px;
        padding: 14px;
        border: 1px solid var(--color-grey-20);
        border-radius: 12px;
        background: var(--color-grey-10);
    }

    .add-device-title {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
        color: var(--color-grey-100);
    }

    .add-device-description {
        margin: 6px 0 12px;
        font-size: 13px;
        color: var(--color-grey-60);
    }

    .add-device-row {
        display: flex;
        gap: 10px;
        align-items: center;
    }

    .add-device-input {
        flex: 1;
        min-width: 0;
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        padding: 10px 12px;
        font-size: 13px;
        color: var(--color-grey-100);
        background: var(--color-grey-0);
    }

    .add-device-input:focus {
        outline: none;
        border-color: var(--color-primary-start);
    }

    .btn-connect {
        white-space: nowrap;
        background: var(--color-grey-15, var(--color-grey-10));
        color: var(--color-font-primary);
        border: 1px solid var(--color-grey-25);
        padding: 10px 16px;
    }

    .btn-connect:hover:not(:disabled) {
        background: var(--color-grey-20);
    }

    .add-device-error {
        margin: 8px 0 0;
        font-size: 12px;
        color: var(--color-error);
    }

    .loading, .empty-state {
        text-align: center;
        padding: 40px 20px;
        color: var(--color-grey-60);
    }

    .sessions-list {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .session-card {
        background: var(--color-grey-10);
        border-radius: 12px;
        padding: 20px;
        border: 1px solid var(--color-grey-20);
        transition: all 0.2s;
    }

    .session-card.current {
        border-color: rgba(59, 130, 246, 0.4);
        background: rgba(59, 130, 246, 0.04);
    }

    .session-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 12px;
    }

    .session-info {
        flex: 1;
    }

    .session-device-name {
        font-size: 18px;
        font-weight: 600;
        margin: 0 0 4px 0;
        color: var(--color-grey-100);
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
    }

    .flag {
        font-size: 20px;
        line-height: 1;
    }

    .current-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 500;
        background: rgba(59, 130, 246, 0.1);
        color: #3b82f6;
        white-space: nowrap;
    }

    .session-location {
        font-size: 14px;
        color: var(--color-grey-60);
        margin: 4px 0 0 0;
    }

    .separator {
        margin: 0 4px;
    }

    .session-details {
        padding-top: 12px;
        border-top: 1px solid var(--color-grey-20);
    }

    .detail-row {
        display: flex;
        justify-content: space-between;
        margin-bottom: 6px;
        font-size: 13px;
    }

    .detail-label {
        color: var(--color-grey-60);
    }

    .detail-value {
        color: var(--color-grey-100);
        font-weight: 500;
    }

    .session-actions {
        display: flex;
        gap: 8px;
        padding-top: 12px;
        border-top: 1px solid var(--color-grey-20);
        margin-top: 12px;
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

    .btn-remove {
        background: rgba(223, 27, 65, 0.1);
        color: #df1b41;
    }

    .btn-remove:hover:not(:disabled) {
        background: rgba(223, 27, 65, 0.2);
    }

    .bulk-actions {
        margin-top: 24px;
        padding-top: 20px;
        border-top: 1px solid var(--color-grey-20);
    }

    .btn-logout-others {
        width: 100%;
        background: rgba(255, 165, 0, 0.1);
        color: #e69500;
        padding: 12px 16px;
    }

    .btn-logout-others:hover:not(:disabled) {
        background: rgba(255, 165, 0, 0.2);
    }

    .btn-logout-all {
        width: 100%;
        background: rgba(223, 27, 65, 0.1);
        color: #df1b41;
        padding: 12px 16px;
    }

    .btn-logout-all:hover:not(:disabled) {
        background: rgba(223, 27, 65, 0.2);
    }

    .destructive-hint {
        font-size: 12px;
        color: var(--color-grey-50);
        margin-top: 8px;
        text-align: center;
    }

    @media (max-width: 768px) {
        .sessions-container {
            padding: 16px;
        }

        .add-device-row {
            flex-direction: column;
            align-items: stretch;
        }

        .session-header {
            flex-direction: column;
        }

        .session-actions {
            flex-direction: column;
        }

        .btn {
            width: 100%;
        }
    }
</style>
