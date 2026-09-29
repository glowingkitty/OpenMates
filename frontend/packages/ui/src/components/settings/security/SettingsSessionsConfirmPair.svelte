<!--
SettingsSessionsConfirmPair — Authorizing device UI for magic pair login.

The already-logged-in device opens this page (via /#pair=TOKEN deep link) to:
  1. See the requesting device's info (name, truncated IP, location)
  2. Choose an auto-logout duration for the new session
  3. Allow or Deny
  4. On Allow: display a 6-character PIN to the user, who relays it to the new device

The PIN, OPAQUE registration, and server role stay on this device. The relay
receives only PAKE messages, a one-use grant hash, and an encrypted key bundle.
-->

<script lang="ts">
    import { onMount, onDestroy, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { get } from 'svelte/store';
    import { createPairContext, createPairApprover, generateGrantSecret, type PairApprover, type PairBundle } from '@repo/pairing-crypto';
    import { uint8ArrayToBase64, getKeyFromStorage, getEmailSalt, getEmailDecryptedWithMasterKey } from '../../../services/cryptoService';
    import { pendingPairToken, newlyPairedSession } from '../../../stores/pairSessionStore';
    import { notificationStore } from '../../../stores/notificationStore';
    import { userProfile } from '../../../stores/userProfile';
    import { pairRequest, pairExpired, resolvePairEmailEnvelope, PAIR_POLL_MS, type PairInfo, type PairPoll, type PairLifetime, type PairAccountCheck } from '../../../services/pairV2';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import SecurityAuth from './SecurityAuth.svelte';

    const dispatch = createEventDispatcher<{ denied: void; done: void; openSettings: { settingsPath: string; direction: string; icon: string; title: string } }>();
    interface RequestingDeviceInfo { device_name: string; ip_truncated: string; country_code: string | null; city: string | null; }
    type PageStatus = 'loading' | 'confirm' | 'step_up' | 'authorizing' | 'pin_display' | 'denied' | 'complete' | 'error' | 'invalid';
    let token = $state('');
    let pageStatus = $state<PageStatus>('loading');
    let deviceInfo = $state<RequestingDeviceInfo | null>(null);
    let info: PairInfo | null = null;
    let approved: PairInfo | null = null;
    let errorMessage = $state('');
    let generatedPin = $state<string | null>(null);
    let autoLogoutMinutes = $state<PairLifetime>(null);
    let approver: PairApprover | null = null;
    let stage: 'waiting' | 'response' | 'authorized' = 'waiting';
    let pollInterval: ReturnType<typeof setInterval> | null = null;
    let polling = false;
    let destroyed = false;
    let generation = 0;
    let hasPasskey = $state(false);
    let hasPassword = $state(false);
    let has2FA = $state(false);
    let pinCopied = $state(false);
    let displayPin = $derived(generatedPin ? `${generatedPin.slice(0, 3)} ${generatedPin.slice(3)}` : '');

    onMount(() => {
        const storedToken = get(pendingPairToken);
        pendingPairToken.set(null);
        if (!storedToken || !/^[A-Z0-9]{6}$/i.test(storedToken)) { pageStatus = 'invalid'; return; }
        token = storedToken.toUpperCase();
        void loadDeviceInfo();
    });
    onDestroy(() => {
        destroyed = true; generation++; stopPolling(); approver?.abort();
        if (approved && pageStatus !== 'complete' && token) void pairRequest(`/${token}`, { method: 'DELETE' }).catch(() => {});
    });
    function stopPolling() { if (pollInterval) clearInterval(pollInterval); pollInterval = null; }
    function fail(message: string) {
        stopPolling(); approver?.abort(); approver = null; generatedPin = null;
        errorMessage = message; pageStatus = 'error';
        if (approved && token) void pairRequest(`/${token}`, { method: 'DELETE' }).catch(() => {});
    }
    async function loadDeviceInfo() {
        pageStatus = 'loading'; errorMessage = '';
        try {
            const data = await pairRequest<PairInfo>(`/info/${token}`);
            if (destroyed) return;
            if (data.protocol_version !== 2 || !data.session_id || !data.receiver_token_hash || pairExpired(data.expires_at)) { pageStatus = 'invalid'; return; }
            info = data;
            deviceInfo = { device_name: data.device_name || 'Unknown device', ip_truncated: data.ip_truncated || '', country_code: data.country_code || null, city: data.city || null };
            const methods = await fetch(getApiEndpoint(apiEndpoints.auth.methods), { credentials: 'include' });
            if (!methods.ok) throw new Error('Could not load authentication methods');
            const auth = await methods.json();
            hasPasskey = !!auth.has_passkey; hasPassword = !!auth.has_password; has2FA = !!auth.has_2fa;
            pageStatus = 'confirm';
        } catch (err) {
            if (!destroyed) { errorMessage = err instanceof Error ? err.message : $text('settings.sessions.pair_confirm_error'); pageStatus = 'error'; }
        }
    }
    async function allow() {
        if (!info || pageStatus !== 'confirm') return;
        const run = generation;
        pageStatus = 'authorizing'; errorMessage = '';
        try {
            const data = await pairRequest<PairInfo & { success: boolean }>(`/approve/${token}`, {
                method: 'POST', body: JSON.stringify({ authorizer_device_name: getAuthorizerDeviceName(), auto_logout_minutes: autoLogoutMinutes }),
            });
            if (destroyed || run !== generation) {
                if (data.success) void pairRequest(`/${token}`, { method: 'DELETE' }).catch(() => {});
                return;
            }
            if (!data.success || data.protocol_version !== 2 || data.session_id !== info.session_id || data.receiver_token_hash !== info.receiver_token_hash || data.auto_logout_minutes !== autoLogoutMinutes || !data.authorizer_user_id || pairExpired(data.expires_at)) throw new Error('Pairing approval mismatch');
            if (data.authorizer_user_id !== get(userProfile).user_id) throw new Error('Pairing account mismatch');
            approved = data;
            const context = createPairContext({ token, session_id: info.session_id, receiver_token_hash: info.receiver_token_hash,
                authorizer_user_id: data.authorizer_user_id, auto_logout_minutes: autoLogoutMinutes });
            const nextApprover = await createPairApprover(context);
            if (destroyed || run !== generation) { nextApprover.abort(); return; }
            approver = nextApprover;
            generatedPin = nextApprover.pin;
            pageStatus = 'pin_display';
            pollInterval = setInterval(() => { void pollStatus(); }, PAIR_POLL_MS);
        } catch (err) {
            if (destroyed || run !== generation) return;
            if ([401, 403, 428].includes((err as { status?: number }).status ?? 0)) {
                pageStatus = 'step_up';
            } else fail(err instanceof Error ? err.message : $text('settings.sessions.pair_confirm_error'));
        }
    }
    async function handleStepUpSuccess() {
        if (pageStatus !== 'step_up') return;
        const run = generation;
        if (destroyed || run !== generation) return;
        // SecurityAuth verifies passkey, TOTP, or password plus one-use email
        // code against the current server session before invoking onSuccess.
        pageStatus = 'confirm';
        await allow();
    }
    async function deny() {
        if (approved) await pairRequest(`/${token}`, { method: 'DELETE' }).catch(() => {});
        pageStatus = 'denied'; dispatch('denied');
    }
    async function pollStatus() {
        if (polling || !approved || !approver || pageStatus !== 'pin_display') return;
        if (pairExpired(approved.expires_at)) { fail($text('settings.sessions.pair_expired')); return; }
        const run = generation;
        polling = true;
        try {
            const data = await pairRequest<PairPoll>(`/authorizer/${token}`);
            if (destroyed || run !== generation) return;
            if (data.status === 'failed' || data.status === 'cancelled') { fail($text('settings.sessions.pair_restart_required')); return; }
            if (data.status === 'request' && data.receiver_request && stage === 'waiting') {
                stage = 'response';
                const response = await approver.receiveRequest(data.receiver_request);
                if (destroyed || run !== generation) return;
                await pairRequest(`/authorizer/${token}/message`, { method: 'POST', body: JSON.stringify({ stage: 'response', message: response }) });
            }
            if (data.status === 'finish' && data.receiver_finish && stage === 'response') {
                stage = 'authorized';
                await approver.verifyFinish(data.receiver_finish);
                if (destroyed || run !== generation) return;
                // The master key is exported only after a valid local PAKE final proof.
                const grant = await generateGrantSecret();
                if (destroyed || run !== generation) return;
                const bundle = await buildBundle(grant.secret);
                if (destroyed || run !== generation) return;
                const encrypted = await approver.encryptBundle(bundle);
                if (destroyed || run !== generation) return;
                await pairRequest(`/authorize/${token}`, { method: 'POST', body: JSON.stringify({ ...encrypted, grant_hash: grant.hash }) });
            }
            if (data.status === 'acknowledged' && stage === 'authorized') {
                stopPolling(); approver.abort(); approver = null; generatedPin = null;
                pageStatus = 'complete'; newlyPairedSession.set(true);
                notificationStore.success(get(text)('settings.sessions.pair_complete_success'));
                dispatch('openSettings', { settingsPath: 'account/security/sessions', direction: 'backward', icon: 'devices', title: get(text)('settings.sessions.title') });
            }
        } catch (err) {
            if (!destroyed && run === generation) fail(err instanceof Error ? err.message : $text('settings.sessions.pair_restart_required'));
        } finally { polling = false; }
    }
    async function buildBundle(grantSecret: string): Promise<PairBundle> {
        if (!approved) throw new Error('Pairing approval missing');
        const masterKey = await getKeyFromStorage();
        if (!masterKey) throw new Error('Master key not found');
        const salt = getEmailSalt();
        if (!salt) throw new Error('Account metadata unavailable');
        const account = await pairRequest<PairAccountCheck>('/account-check');
        if (account.user_id !== approved.authorizer_user_id || account.user_id !== get(userProfile).user_id ||
            account.user_email_salt !== uint8ArrayToBase64(salt)) throw new Error('Pairing account mismatch');
        const localEmail = account.encrypted_email_with_master_key ? null : await getEmailDecryptedWithMasterKey();
        const encryptedEmail = await resolvePairEmailEnvelope(account, masterKey, localEmail);
        const master_key_exported = uint8ArrayToBase64(new Uint8Array(await crypto.subtle.exportKey('raw', masterKey)));
        return { protocol_version: 2, master_key_exported, grant_secret: grantSecret, user_email_salt: uint8ArrayToBase64(salt),
            hashed_email: account.hashed_email, user_id: approved.authorizer_user_id!,
            account_context: { encrypted_email_with_master_key: encryptedEmail } };
    }
    function getAuthorizerDeviceName(): string {
        const ua = navigator.userAgent;
        if (/iPhone/.test(ua)) return 'iPhone'; if (/iPad/.test(ua)) return 'iPad';
        if (/Android/.test(ua)) return 'Android device'; if (/Mac/.test(ua)) return 'Mac';
        if (/Windows/.test(ua)) return 'Windows PC'; if (/Linux/.test(ua)) return 'Linux PC'; return 'Desktop';
    }
    function formatLocation(info: RequestingDeviceInfo): string {
        const parts: string[] = [];
        if (info.city) parts.push(info.city);
        if (info.country_code) { try { parts.push(new Intl.DisplayNames(['en'], { type: 'region' }).of(info.country_code.toUpperCase()) || info.country_code); } catch { parts.push(info.country_code); } }
        if (info.ip_truncated) parts.push(info.ip_truncated);
        return parts.join(' · ') || 'Unknown location';
    }
    async function copyPin() {
        if (!generatedPin) return;
        try { await navigator.clipboard.writeText(generatedPin); pinCopied = true; setTimeout(() => { pinCopied = false; }, 2000); } catch { /* unavailable */ }
    }
</script>

<div class="confirm-pair-container">

    {#if pageStatus === 'loading'}
        <p class="status-text">{$text('settings.sessions.loading')}</p>

    {:else if pageStatus === 'invalid'}
        <div class="error-box">
            <p>{$text('settings.sessions.pair_invalid_token')}</p>
        </div>

    {:else if pageStatus === 'error'}
        <div class="error-box">
            <p>{errorMessage}</p>
        </div>
        <button class="btn btn-secondary" onclick={() => loadDeviceInfo()}>
            {$text('settings.sessions.pair_refresh')}
        </button>

    {:else if pageStatus === 'confirm' && deviceInfo}
        <h2 class="page-title">{$text('settings.sessions.pair_confirm_title')}</h2>
        <p class="page-description">{$text('settings.sessions.pair_confirm_description')}</p>

        <!-- Requesting device card -->
        <div class="device-card">
            <p class="device-card-label">{$text('settings.sessions.pair_confirm_requesting_device')}</p>
            <p class="device-name">{deviceInfo.device_name}</p>
            <p class="device-location">{formatLocation(deviceInfo)}</p>
        </div>

        <!-- Auto-logout selector -->
        <div class="auto-logout-row">
            <label class="auto-logout-label" for="confirm-pair-auto-logout">
                {$text('settings.sessions.pair_confirm_auto_logout_label')}
            </label>
            <select
                id="confirm-pair-auto-logout"
                class="auto-logout-select"
                bind:value={autoLogoutMinutes}
            >
                <option value={null}>{$text('settings.sessions.pair_auto_logout_none')}</option>
                <option value={30}>{$text('settings.sessions.pair_auto_logout_30m')}</option>
                <option value={60}>{$text('settings.sessions.pair_auto_logout_1h')}</option>
                <option value={240}>{$text('settings.sessions.pair_auto_logout_4h')}</option>
                <option value={480}>{$text('settings.sessions.pair_auto_logout_8h')}</option>
                <option value={1440}>{$text('settings.sessions.pair_auto_logout_24h')}</option>
            </select>
        </div>

        <!-- Actions -->
        <div class="action-row">
            <button class="btn btn-deny" onclick={() => deny()}>
                {$text('settings.sessions.pair_confirm_deny')}
            </button>
            <button class="btn btn-allow" data-testid="pair-allow-button" onclick={() => allow()}>
                {$text('settings.sessions.pair_confirm_allow')}
            </button>
        </div>

    {:else if pageStatus === 'authorizing'}
        <p class="status-text">{$text('settings.sessions.pair_confirm_allowing')}</p>

    {:else if pageStatus === 'step_up'}
        <SecurityAuth
            {hasPasskey}
            {hasPassword}
            {has2FA}
            autoStart={false}
            sensitiveActionPurpose="pair_approval"
            title={$text('settings.sessions.pair_step_up_title')}
            description={$text('settings.sessions.pair_step_up_description')}
            onSuccess={() => { void handleStepUpSuccess(); }}
            onFailed={(message) => { errorMessage = message; }}
            onCancel={() => { pageStatus = 'confirm'; }}
        />

    {:else if pageStatus === 'pin_display' && generatedPin}
        <p class="page-description">{$text('settings.sessions.pair_confirm_pin_hint')}</p>
        <p class="status-text">{$text('settings.sessions.pair_keep_open')}</p>

        <div class="pin-display-row">
            <span class="pin-display" data-testid="pair-pin-display">{displayPin}</span>
            <button
                class="btn-copy"
                onclick={copyPin}
                title="Copy PIN"
                aria-label="Copy PIN"
            >
                {#if pinCopied}
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                {:else}
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                {/if}
            </button>
        </div>

        <button class="btn btn-secondary" onclick={() => {
            stopPolling();
            approver?.abort(); approver = null;
            if (token) {
                void pairRequest(`/${token}`, { method: 'DELETE' }).catch(() => {});
            }
            dispatch('done');
        }}>
            {$text('common.cancel')}
        </button>

    {:else if pageStatus === 'denied'}
        <div class="info-box">
            <p>{$text('settings.sessions.pair_confirm_denied')}</p>
        </div>
    {/if}

</div>

<style>
    .confirm-pair-container {
        width: 100%;
        padding: 1.25rem;
        max-width: 480px;
        margin: 0 auto;
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }

    .page-title {
        font-size: var(--font-size-h3);
        font-weight: 600;
        margin: 0;
        color: var(--color-font-primary);
    }

    .page-description {
        font-size: var(--font-size-p);
        color: var(--color-font-secondary);
        margin: 0;
    }

    .status-text {
        text-align: center;
        color: var(--color-font-secondary);
        font-size: var(--processing-details-font-size);
    }

    .device-card {
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-25);
        border-radius: var(--radius-5);
        padding: 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .device-card-label {
        font-size: var(--processing-details-font-size);
        color: var(--color-font-secondary);
        margin: 0;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    .device-name {
        font-size: var(--font-size-p);
        font-weight: 600;
        color: var(--color-font-primary);
        margin: 0;
    }

    .device-location {
        font-size: var(--processing-details-font-size);
        color: var(--color-font-secondary);
        margin: 0;
    }

    .auto-logout-row {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        flex-wrap: wrap;
    }

    .auto-logout-label {
        font-size: var(--processing-details-font-size);
        color: var(--color-font-secondary);
        white-space: nowrap;
    }

    .auto-logout-select {
        flex: 1;
        min-width: 160px;
        padding: 0.4rem 0.6rem;
        border-radius: var(--radius-3);
        border: 1px solid var(--color-grey-30);
        background: var(--color-grey-10);
        color: var(--color-font-primary);
        font-size: var(--processing-details-font-size);
        cursor: pointer;
    }

    .action-row {
        display: flex;
        gap: 0.75rem;
    }

    .pin-display-row {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-25);
        border-radius: var(--radius-5);
        padding: 1rem 1.25rem;
    }

    .pin-display {
        flex: 1;
        font-size: 2.5rem;
        font-weight: 700;
        letter-spacing: 0.25em;
        color: var(--color-font-primary);
        font-variant-numeric: tabular-nums;
        font-family: monospace;
        text-align: center;
        user-select: text;
        -webkit-user-select: text;
        cursor: text;
    }

    .btn-copy {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        width: 2.25rem;
        height: 2.25rem;
        border-radius: var(--radius-3);
        border: 1px solid var(--color-grey-30);
        background: var(--color-grey-0);
        color: var(--color-font-secondary);
        cursor: pointer;
        transition: background var(--duration-fast), color var(--duration-fast), border-color var(--duration-fast);
    }

    .btn-copy:hover {
        background: var(--color-grey-20);
        color: var(--color-font-primary);
        border-color: var(--color-grey-40);
    }

    .btn-copy:active {
        background: var(--color-grey-25);
    }

    .error-box {
        background: rgba(223, 27, 65, 0.08);
        border: 1px solid rgba(223, 27, 65, 0.25);
        border-radius: var(--radius-3);
        padding: 0.75rem 1rem;
        font-size: var(--processing-details-font-size);
        color: var(--color-error);
    }

    .info-box {
        background: rgba(59, 130, 246, 0.07);
        border: 1px solid rgba(59, 130, 246, 0.25);
        border-radius: var(--radius-3);
        padding: 0.75rem 1rem;
        font-size: var(--processing-details-font-size);
        color: var(--color-font-primary);
    }

    .btn {
        padding: 0.65rem 1.25rem;
        border-radius: var(--radius-3);
        font-size: var(--button-font-size);
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition: opacity var(--duration-fast);
        flex: 1;
    }

    .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .btn-allow {
        background: var(--color-primary);
        color: var(--color-grey-0);
    }

    .btn-allow:hover:not(:disabled) {
        opacity: 0.88;
    }

    .btn-deny {
        background: var(--color-grey-20);
        color: var(--color-font-primary);
    }

    .btn-deny:hover:not(:disabled) {
        background: var(--color-grey-25);
    }

    .btn-secondary {
        background: var(--color-grey-20);
        color: var(--color-font-primary);
        flex: unset;
    }

    .btn-secondary:hover:not(:disabled) {
        background: var(--color-grey-25);
    }
</style>
