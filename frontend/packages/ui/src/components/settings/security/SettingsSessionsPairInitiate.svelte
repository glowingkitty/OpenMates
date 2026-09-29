<!--
SettingsSessionsPairInitiate — Initiating device UI for magic pair login.

Generates a receiver capability, displays the routing token/QR code, and uses a
locally entered PIN for client-to-client PAKE. The v2 completion endpoint creates
the ordinary session only after the encrypted bundle is verified.

Architecture: docs/architecture/device-sessions.md
Client-side encryption: docs/architecture/core/client-side-encryption.md
-->

<script lang="ts">
    import { onMount, onDestroy, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { createPairContext, createPairReceiver, generateReceiverCapability, type PairReceiver, type PairBundle } from '@repo/pairing-crypto';
    import { base64ToUint8Array, saveKeyToSession, saveEmailSalt, saveEmailEncryptedWithMasterKey,
        hashEmail, clearKeyFromStorage } from '../../../services/cryptoService';
    import { decryptWithMasterKeyDirect } from '../../../services/encryption/MetadataEncryptor';
    import { logout } from '../../../stores/authStore';
    import { activatePairSession } from '../../../stores/pairSessionStore';
    import { getSessionId } from '../../../utils/sessionId';
    import { setWebSocketToken } from '../../../utils/cookies';
    import { userDB } from '../../../services/userDB';
    import type { User } from '../../../types/user';
    import { pairRequest, pairExpired, PAIR_POLL_MS, type PairInfo, type PairPoll } from '../../../services/pairV2';
    import QRCodeSVG from 'qrcode-svg';

    const dispatch = createEventDispatcher<{ login: { user: User | null } }>();
    interface Props { stayLoggedIn?: boolean; }
    const { stayLoggedIn = false }: Props = $props();
    type PairStatus = 'generating' | 'waiting' | 'ready' | 'expired' | 'error' | 'complete';
    type PinStatus = 'idle' | 'submitting' | 'error' | 'locked';
    let pairToken = $state<string | null>(null);
    let pairUrl = $state('');
    let qrSvg = $state('');
    let pairStatus = $state<PairStatus>('generating');
    let errorMessage = $state('');
    let copied = $state(false);
    let pinValue = $state('');
    let pinStatus = $state<PinStatus>('idle');
    let pinErrorMessage = $state('');
    let _pinAttemptsRemaining = $state<number | null>(null);
    let completedUser: User | null = null;
    let capability: { secret: string; hash: string } | null = null;
    let receiver: PairReceiver | null = null;
    let expiresAt = 0;
    let pollInterval: ReturnType<typeof setInterval> | null = null;
    let polling = false;
    let destroyed = false;
    let generation = 0;
    const QR_SIZE = 200;

    onMount(() => { void initiatePairing(); });
    onDestroy(() => {
        destroyed = true;
        generation++;
        stopPolling();
        receiver?.abort();
        if (pairToken && capability && pairStatus !== 'complete') {
            void pairRequest(`/${pairToken}`, { method: 'DELETE' }, capability.secret).catch(() => {});
        }
    });

    async function initiatePairing() {
        if (pairStatus === 'generating' && pairToken) return;
        generation++;
        const run = generation;
        stopPolling();
        receiver?.abort(); receiver = null;
        if (pairToken && capability && pairStatus !== 'complete') {
            void pairRequest(`/${pairToken}`, { method: 'DELETE' }, capability.secret).catch(() => {});
        }
        pairStatus = 'generating'; errorMessage = ''; pairToken = null; qrSvg = '';
        pinValue = ''; pinStatus = 'idle'; pinErrorMessage = ''; _pinAttemptsRemaining = null;
        try {
            capability = await generateReceiverCapability();
            if (destroyed || run !== generation) return;
            const localCapability = capability;
            const data = await pairRequest<{ protocol_version: number; token: string; expires_at: number }>('/initiate', {
                method: 'POST', credentials: 'omit',
                body: JSON.stringify({ receiver_token_hash: capability.hash, session_id: getSessionId() }),
            });
            if (destroyed || run !== generation) {
                if (data.token) void pairRequest(`/${data.token}`, { method: 'DELETE' }, localCapability.secret).catch(() => {});
                return;
            }
            if (data.protocol_version !== 2 || !/^[A-Z0-9]{6}$/i.test(data.token) || pairExpired(data.expires_at)) throw new Error('Invalid pairing response');
            pairToken = data.token.toUpperCase(); expiresAt = data.expires_at;
            pairUrl = `${window.location.origin}/#pair=${pairToken}`;
            generateQR(pairUrl);
            pairStatus = 'waiting';
            pollInterval = setInterval(() => { void pollStatus(); }, PAIR_POLL_MS);
        } catch (err: unknown) {
            if (destroyed || run !== generation) return;
            errorMessage = err instanceof Error ? err.message : $text('settings.sessions.pair_confirm_error');
            pairStatus = 'error';
        }
    }

    function generateQR(url: string) {
        try {
            qrSvg = new QRCodeSVG({ content: url, padding: 4, width: QR_SIZE, height: QR_SIZE, color: '#000000', background: '#ffffff', ecl: 'M' }).svg();
        } catch { qrSvg = ''; }
    }
    function stopPolling() { if (pollInterval) clearInterval(pollInterval); pollInterval = null; }
    function failPairing(message: string, expired = false) {
        stopPolling(); receiver?.abort(); receiver = null;
        pinValue = ''; pinStatus = 'locked';
        pairStatus = expired ? 'expired' : 'error'; errorMessage = message;
        if (pairToken && capability) void pairRequest(`/${pairToken}`, { method: 'DELETE' }, capability.secret).catch(() => {});
    }
    async function pollStatus() {
        if (polling || !pairToken || !capability || pairStatus === 'complete' || pairStatus === 'expired' || pairStatus === 'error') return;
        if (pairExpired(expiresAt)) { failPairing($text('settings.sessions.pair_expired'), true); return; }
        const run = generation;
        polling = true;
        try {
            const data = await pairRequest<PairPoll>(`/receiver/${pairToken}`, {}, capability.secret);
            if (destroyed || run !== generation) return;
            if (data.status === 'failed' || data.status === 'cancelled') { failPairing($text('settings.sessions.pair_restart_required')); return; }
            if (data.status === 'approved' && pairStatus === 'waiting') {
                if (data.session_id !== getSessionId() || data.receiver_token_hash !== capability.hash || !data.authorizer_user_id || data.auto_logout_minutes === undefined) {
                    failPairing($text('settings.sessions.pair_confirm_error')); return;
                }
                approvedInfo = data as PairInfo;
                pairStatus = 'ready';
                if (pinValue.length === 6) void submitPin();
            }
            if (data.status === 'response' && receiver && data.message && stage === 'request') {
                stage = 'processing';
                const finish = await receiver.receiveResponse(data.message);
                if (destroyed || run !== generation) return;
                await pairRequest(`/receiver/${pairToken}/message`, { method: 'POST', body: JSON.stringify({ stage: 'finish', message: finish }) }, capability.secret);
                if (destroyed || run !== generation) return;
                stage = 'finish';
            }
            if (data.status === 'ready' && receiver && stage === 'finish' && data.encrypted_bundle && data.iv) {
                stage = 'completing'; stopPolling();
                await completePair(data.encrypted_bundle, data.iv);
            }
        } catch (err) {
            if (destroyed || run !== generation) return;
            // A transient poll error may recover; local expiry still bounds it.
            if (stage !== 'idle') failPairing(err instanceof Error ? err.message : $text('settings.sessions.pair_restart_required'));
        } finally { polling = false; }
    }
    let approvedInfo: PairInfo | null = null;
    let stage: 'idle' | 'request' | 'processing' | 'finish' | 'completing' = 'idle';
    async function submitPin() {
        if (!pairToken || !capability || !approvedInfo || stage !== 'idle' || pairStatus !== 'ready' || !/^[A-Z0-9]{6}$/.test(pinValue)) return;
        if (pairExpired(expiresAt)) { failPairing($text('settings.sessions.pair_expired'), true); return; }
        pinStatus = 'submitting'; pinErrorMessage = '';
        const run = generation;
        try {
            const context = createPairContext({ token: pairToken, session_id: getSessionId(), receiver_token_hash: capability.hash,
                authorizer_user_id: approvedInfo.authorizer_user_id!, auto_logout_minutes: approvedInfo.auto_logout_minutes! });
            const nextReceiver = await createPairReceiver(context, pinValue);
            if (destroyed || run !== generation) { nextReceiver.abort(); return; }
            receiver = nextReceiver;
            pinValue = '';
            stage = 'request';
            await pairRequest(`/receiver/${pairToken}/message`, { method: 'POST', body: JSON.stringify({ stage: 'request', message: receiver.request }) }, capability.secret);
        } catch (err) {
            failPairing(err instanceof Error ? err.message : $text('settings.sessions.pair_restart_required'));
        }
    }
    async function completePair(encrypted: string, iv: string) {
        if (!receiver || !pairToken || !capability || !approvedInfo) return;
        const run = generation;
        let sessionMinted = false;
        let acknowledged = false;
        try {
            const bundle: PairBundle = await receiver.decryptBundle(encrypted, iv);
            if (destroyed || run !== generation) return;
            if (bundle.protocol_version !== 2 || bundle.user_id !== approvedInfo.authorizer_user_id || !bundle.grant_secret || !bundle.master_key_exported || !bundle.user_email_salt) throw new Error('Pairing account mismatch');
            const raw = new Uint8Array(base64ToUint8Array(bundle.master_key_exported)).buffer as ArrayBuffer;
            const masterKey = await crypto.subtle.importKey('raw', raw, { name: 'AES-GCM' }, true, ['encrypt', 'decrypt']);
            const encryptedEmail = bundle.account_context?.encrypted_email_with_master_key;
            if (!encryptedEmail) throw new Error('Pairing account metadata missing');
            const email = await decryptWithMasterKeyDirect(encryptedEmail, masterKey);
            if (!email || await hashEmail(email) !== bundle.hashed_email) throw new Error('Pairing account identity mismatch');
            if (destroyed || run !== generation) return;
            const result = await pairRequest<{ success: boolean; user?: User; ws_token?: string; pair_expires_at?: number | null }>(`/complete/${pairToken}`, {
                method: 'POST', body: JSON.stringify({ grant_secret: bundle.grant_secret }),
            }, capability.secret);
            sessionMinted = true;
            if (destroyed || run !== generation) throw new Error('Pairing page closed');
            if (!result.success || result.user?.id !== bundle.user_id) throw new Error('Pairing session mismatch');
            if (approvedInfo.auto_logout_minutes != null) {
                const deadline = result.pair_expires_at;
                const latestAllowed = Date.now() / 1000 + approvedInfo.auto_logout_minutes * 60 + 30;
                if (!deadline || pairExpired(deadline) || deadline > latestAllowed) throw new Error('Pairing deadline mismatch');
            } else if (result.pair_expires_at != null) throw new Error('Unexpected pairing deadline');
            await saveKeyToSession(masterKey, stayLoggedIn);
            saveEmailSalt(base64ToUint8Array(bundle.user_email_salt), stayLoggedIn);
            if (!await saveEmailEncryptedWithMasterKey(email, stayLoggedIn)) throw new Error('Paired email was not stored');
            if (!result.user || !result.ws_token) throw new Error('Pairing session data missing');
            await userDB.saveUserData(result.user);
            if (destroyed || run !== generation) throw new Error('Pairing page closed');
            if ((await userDB.getUserData())?.id !== bundle.user_id) throw new Error('Paired profile was not stored');
            setWebSocketToken(result.ws_token);
            activatePairSession({ authorizerDeviceName: approvedInfo.authorizer_device_name ?? null,
                autoLogoutMinutes: approvedInfo.auto_logout_minutes ?? null, pairExpiresAt: result.pair_expires_at ?? null });
            await acknowledgeWithRetry(pairToken, capability.secret, run);
            acknowledged = true;
            if (destroyed || run !== generation) throw new Error('Pairing page closed');
            // ACK is the server activation boundary. Parent Login hydrates auth
            // after this event, so an auth refresh cannot unmount us before delivery.
            pairStatus = 'complete'; stopPolling(); receiver.abort(); receiver = null;
            capability = null; pinStatus = 'idle'; completedUser = result.user;
            dispatch('login', { user: completedUser });
        } catch (err) {
            if (sessionMinted && !acknowledged) {
                if (pairToken && capability) await pairRequest(`/${pairToken}`, { method: 'DELETE' }, capability.secret).catch(() => {});
                await clearKeyFromStorage().catch(() => {});
                await logout({ skipServerLogout: true }).catch(() => false);
            }
            failPairing(err instanceof Error ? err.message : $text('settings.sessions.pair_restart_required'));
        }
    }
    async function acknowledgeWithRetry(token: string, receiverSecret: string, run: number): Promise<void> {
        let lastError: unknown;
        for (let attempt = 0; attempt < 3; attempt++) {
            if (destroyed || run !== generation) throw new Error('Pairing page closed');
            try {
                await pairRequest(`/acknowledge/${token}`, { method: 'POST', body: '{}' }, receiverSecret);
                return;
            } catch (err) {
                lastError = err;
                if ([400, 401, 403].includes((err as { status?: number }).status ?? 0)) break;
                if (attempt < 2) await new Promise(resolve => setTimeout(resolve, 250));
            }
        }
        try {
            const state = await pairRequest<PairPoll>(`/receiver/${token}`, {}, receiverSecret);
            if (state.status === 'acknowledged') return;
        } catch { /* The result remains uncertain until a new connection. */ }
        throw lastError instanceof Error ? lastError : new Error('Pairing acknowledgement failed');
    }
    function retryLogin() { if (pairStatus === 'complete' && completedUser) dispatch('login', { user: completedUser }); }
    async function copyLink() {
        if (!pairUrl) return;
        try { await navigator.clipboard.writeText(pairUrl); copied = true; setTimeout(() => { copied = false; }, 2000); } catch { /* unavailable */ }
    }
    function handlePinInput(e: Event) {
        const target = e.target as HTMLInputElement;
        pinValue = target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6);
        target.value = pinValue; pinErrorMessage = '';
        if (pairStatus === 'ready' && pinValue.length === 6 && stage === 'idle') void submitPin();
    }
</script>

<div class="pair-initiate-container">
    {#if pairStatus === 'generating'}
        <div class="status-generating">
            <p class="status-text">{$text('settings.sessions.pair_generating')}</p>
        </div>

    {:else if pairStatus === 'error'}
        <div class="error-box">
            <p>{errorMessage}</p>
        </div>
        <button class="btn btn-secondary" data-testid="pair-receiver-refresh" onclick={initiatePairing}>
            {$text('settings.sessions.pair_refresh')}
        </button>

    {:else if pairStatus === 'expired'}
        <div class="info-box">
            <p>{$text('settings.sessions.pair_expired')}</p>
        </div>
        <button class="btn btn-secondary" data-testid="pair-receiver-refresh" onclick={initiatePairing}>
            {$text('settings.sessions.pair_refresh')}
        </button>

    {:else if pairStatus === 'complete'}
        <p class="status-text">{$text('settings.sessions.pair_finalizing')}</p>
        <button class="btn btn-secondary" onclick={retryLogin}>{$text('settings.sessions.pair_retry_open')}</button>

    {:else if pairStatus === 'waiting' || pairStatus === 'ready'}
        <p class="scan-label">📷 Scan code:</p>
        <p class="status-text" data-testid="pair-receiver-code">{pairToken}</p>
        <p class="status-text">{$text('settings.sessions.pair_keep_open')}</p>

        <!-- QR Code -->
        {#if qrSvg}
            <div class="qr-wrapper">
                <div class="qr-svg-container" aria-label="QR code for pairing">
                    <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                    {@html qrSvg}
                </div>
            </div>
        {/if}

        <!-- PIN entry (same screen, directly under QR) -->
        <div class="pin-section">
            <h3 class="pin-title">{$text('settings.sessions.pair_enter_pin_title')}</h3>
            <p class="pin-description">{$text('settings.sessions.pair_enter_pin_description')}</p>

            {#if pinErrorMessage}
                <div class="error-box">{pinErrorMessage}</div>
            {/if}

            {#if pinStatus !== 'locked'}
                <input
                    data-testid="pair-receiver-pin-input"
                    type="text"
                    inputmode="text"
                    maxlength="6"
                    class="pin-input"
                    placeholder={$text('settings.sessions.pair_pin_placeholder')}
                    value={pinValue}
                    oninput={handlePinInput}
                    disabled={pinStatus === 'submitting'}
                    autocomplete="off"
                    autocapitalize="characters"
                />
                {#if pinStatus === 'submitting'}
                    <p class="status-text">{$text('settings.sessions.pair_logging_in')}</p>
                {/if}
            {/if}
        </div>

        <!-- URL + copy -->
        <div class="url-section">
            <p class="url-label">{$text('settings.sessions.pair_url_label')}</p>
            <div class="url-row">
                <span class="url-text">{pairUrl}</span>
                <button class="btn btn-copy" onclick={copyLink}>
                    {copied
                        ? $text('common.not_found.url_copied')
                        : $text('settings.sessions.pair_copy_link')}
                </button>
            </div>
        </div>
    {/if}
</div>

<style>
    .pair-initiate-container {
        width: 100%;
        padding: 1.25rem;
        max-width: 480px;
        margin: 0 auto;
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }

    .status-generating,
    .status-text {
        text-align: center;
        color: var(--color-font-secondary);
        font-size: var(--processing-details-font-size);
    }

    .scan-label {
        margin: 0;
        text-align: center;
        color: var(--color-font-primary);
        font-size: var(--font-size-p);
        font-weight: 600;
    }

    .qr-wrapper {
        display: flex;
        justify-content: center;
    }

    .qr-svg-container {
        border-radius: var(--radius-5);
        overflow: hidden;
        border: 1px solid var(--color-grey-25);
        line-height: 0; /* collapse whitespace around inline SVG */
    }

    .url-section {
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-25);
        border-radius: var(--radius-4);
        padding: 0.75rem;
    }

    .url-label {
        font-size: var(--processing-details-font-size);
        color: var(--color-font-secondary);
        margin: 0 0 0.4rem;
    }

    .url-row {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        flex-wrap: wrap;
    }

    .url-text {
        flex: 1;
        font-size: 0.75rem;
        color: var(--color-font-secondary);
        word-break: break-all;
        font-family: monospace;
    }

    .info-box {
        background: rgba(59, 130, 246, 0.07);
        border: 1px solid rgba(59, 130, 246, 0.25);
        border-radius: var(--radius-3);
        padding: 0.75rem 1rem;
        font-size: var(--processing-details-font-size);
        color: var(--color-font-primary);
    }

    .error-box {
        background: rgba(223, 27, 65, 0.08);
        border: 1px solid rgba(223, 27, 65, 0.25);
        border-radius: var(--radius-3);
        padding: 0.75rem 1rem;
        font-size: var(--processing-details-font-size);
        color: var(--color-error);
    }

    /* PIN section */
    .pin-section {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }

    .pin-title {
        font-size: var(--font-size-h4);
        font-weight: 600;
        margin: 0;
        color: var(--color-font-primary);
    }

    .pin-description {
        font-size: var(--processing-details-font-size);
        color: var(--color-font-secondary);
        margin: 0;
    }

    .pin-input {
        width: 100%;
        padding: 0.75rem 1rem;
        border-radius: var(--radius-4);
        border: 1px solid var(--color-grey-30);
        background: var(--color-grey-10);
        color: var(--color-font-primary);
        font-size: 1.5rem;
        font-family: monospace;
        letter-spacing: 0.3em;
        text-align: center;
        box-sizing: border-box;
    }

    .pin-input:focus {
        border-color: var(--color-primary);
    }

    .pin-input:disabled {
        opacity: 0.6;
    }

    /* Buttons */
    .btn {
        padding: 0.6rem 1.25rem;
        border-radius: var(--radius-3);
        font-size: var(--button-font-size);
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition: opacity var(--duration-fast);
    }

    .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .btn-secondary {
        background: var(--color-grey-20);
        color: var(--color-font-primary);
    }

    .btn-secondary:hover:not(:disabled) {
        background: var(--color-grey-25);
    }

    .btn-copy {
        background: var(--color-grey-20);
        color: var(--color-font-primary);
        padding: 0.35rem 0.75rem;
        font-size: 0.75rem;
        white-space: nowrap;
    }

    .btn-copy:hover {
        background: var(--color-grey-25);
    }
</style>
