<!--
SettingsSessionsPairInitiate — Initiating device UI for magic pair login.

Generates a 6-char token, displays QR code + URL + styled pair code, polls for
authorization, then prompts for the 6-digit PIN to decrypt the session bundle and
complete login via the standard auth flow.

Architecture: docs/architecture/device-sessions.md
Zero-knowledge crypto: docs/architecture/zero-knowledge-storage.md
-->

<script lang="ts">
    import { onMount, onDestroy, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint } from '../../../config/api';
    import { base64ToUint8Array } from '../../../services/cryptoService';
    import { activatePairSession } from '../../../stores/pairSessionStore';
    import QRCodeSVG from 'qrcode-svg';

    const dispatch = createEventDispatcher<{ login: { lookupHash: string; userEmailSalt: string; encryptedKey: string; salt: string; authorizerDeviceName: string | null; autoLogoutMinutes: number | null } }>();

    // ========================================================================
    // TYPES
    // ========================================================================

    type PairStatus = 'generating' | 'waiting' | 'ready' | 'expired' | 'error';
    type PinStatus = 'idle' | 'submitting' | 'error' | 'locked';

    // ========================================================================
    // STATE
    // ========================================================================

    let pairToken = $state<string | null>(null);
    let pairUrl = $state('');
    let qrSvg = $state('');
    let pairStatus = $state<PairStatus>('generating');
    let errorMessage = $state('');
    let copied = $state(false);

    // PIN entry (shown once status = 'ready')
    let pinValue = $state('');
    let pinStatus = $state<PinStatus>('idle');
    let pinErrorMessage = $state('');
    let _pinAttemptsRemaining = $state<number | null>(null);

    let pollInterval: ReturnType<typeof setInterval> | null = null;
    const POLL_INTERVAL_MS = 3000;
    const QR_SIZE = 200;

    // ========================================================================
    // COMPUTED
    // ========================================================================

    // ========================================================================
    // LIFECYCLE
    // ========================================================================

    onMount(async () => {
        await initiatePairing();
    });

    onDestroy(() => {
        stopPolling();
    });

    // ========================================================================
    // CORE FLOW
    // ========================================================================

    async function initiatePairing() {
        pairStatus = 'generating';
        errorMessage = '';
        pairToken = null;
        qrSvg = '';
        pinValue = '';
        pinStatus = 'idle';
        pinErrorMessage = '';

        try {
            const response = await fetch(getApiEndpoint('/v1/auth/pair/initiate'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}),
                // NOTE: intentionally NOT using credentials:include — this endpoint is unauthenticated
            });

            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.detail || 'Failed to generate pair code');
            }

            const data = await response.json();
            pairToken = (data.token as string).toUpperCase();
            pairUrl = `${window.location.origin}/#pair=${pairToken}`;

            generateQR(pairUrl);
            pairStatus = 'waiting';
            startPolling();
        } catch (err: unknown) {
            console.error('[PairInitiate] Failed to initiate pairing:', err);
            errorMessage = err instanceof Error ? err.message : 'Failed to generate code';
            pairStatus = 'error';
        }
    }

    function generateQR(url: string) {
        try {
            const qr = new QRCodeSVG({
                content: url,
                padding: 4,
                width: QR_SIZE,
                height: QR_SIZE,
                color: '#000000',
                background: '#ffffff',
                ecl: 'M',
            });
            qrSvg = qr.svg();
        } catch (err) {
            console.error('[PairInitiate] QR generation failed:', err);
            qrSvg = '';
        }
    }

    function startPolling() {
        stopPolling();
        pollInterval = setInterval(pollStatus, POLL_INTERVAL_MS);
    }

    function stopPolling() {
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
    }

    async function pollStatus() {
        if (!pairToken || pairStatus === 'ready' || pairStatus === 'expired') {
            stopPolling();
            return;
        }

        try {
            const response = await fetch(getApiEndpoint(`/v1/auth/pair/poll/${pairToken}`), {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' },
            });

            if (response.status === 404) {
                // Token expired or not found
                pairStatus = 'expired';
                stopPolling();
                return;
            }

            if (!response.ok) {
                // Non-fatal — keep polling
                return;
            }

            const data = await response.json();
            if (data.status === 'ready') {
                pairStatus = 'ready';
                stopPolling();
                if (pinValue.length === 6 && pinStatus !== 'submitting' && pinStatus !== 'locked') {
                    await submitPin();
                }
            } else if (data.status === 'expired') {
                pairStatus = 'expired';
                stopPolling();
            }
            // status === 'waiting' → keep polling
        } catch {
            // Network error — keep polling silently
        }
    }

    // ========================================================================
    // PIN SUBMISSION
    // ========================================================================

    async function submitPin() {
        if (!pairToken || pinValue.length !== 6 || !/^[A-Z0-9]{6}$/.test(pinValue)) return;

        pinStatus = 'submitting';
        pinErrorMessage = '';

        try {
            const response = await fetch(getApiEndpoint(`/v1/auth/pair/complete/${pairToken}`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pin: pinValue }),
            });

            const data = await response.json().catch(() => ({}));

            if (!response.ok) {
                const msg = (data.message as string) || '';
                if (msg === 'too_many_attempts') {
                    pinStatus = 'locked';
                    pinErrorMessage = $text('settings.sessions.pair_pin_locked');
                    return;
                }
                // Parse remaining attempts from message format "invalid_pin:N_attempts_left"
                const remainingMatch = msg.match(/invalid_pin:(\d+)_attempts_left/);
                const remaining = remainingMatch ? parseInt(remainingMatch[1], 10) : null;
                pinStatus = 'error';
                _pinAttemptsRemaining = remaining;
                pinErrorMessage = $text('settings.sessions.pair_pin_error').replace(
                    '{n}',
                    String(remaining ?? '?')
                );
                pinValue = '';
                return;
            }

            if (!data.success) {
                pinStatus = 'error';
                pinErrorMessage = 'Login failed. Please try again.';
                return;
            }

            // Success — encrypted_bundle and iv are separate
            const encryptedBundleB64 = data.encrypted_bundle as string;
            const ivB64 = data.iv as string;
            const authorizerDeviceName = (data.authorizer_device_name as string | null) ?? null;
            const returnedAutoLogoutMinutes = (data.auto_logout_minutes as number | null) ?? null;

            // Decrypt the bundle with the PIN
            await decryptAndLogin(encryptedBundleB64, ivB64, pinValue, authorizerDeviceName, returnedAutoLogoutMinutes);
        } catch (err: unknown) {
            console.error('[PairInitiate] PIN submission failed:', err);
            pinStatus = 'error';
            pinErrorMessage = err instanceof Error ? err.message : 'Login failed';
        }
    }

    /**
     * Decrypt the bundle using the PIN.
     * Crypto: AES-256-GCM, key derived via PBKDF2(PIN, token-as-salt, 100_000 iters, SHA-256)
     * Must match exactly what SettingsSessionsConfirmPair uses to encrypt.
     *
     * Bundle plaintext JSON: { lookup_hash, user_email_salt, encrypted_key, salt }
     */
    async function decryptAndLogin(
        encryptedBundleB64: string,
        ivB64: string,
        pin: string,
        authorizerDeviceName: string | null,
        returnedAutoLogoutMinutes: number | null,
    ) {
        if (!pairToken) return;

        try {
            const upperToken = pairToken.toUpperCase();

            // Derive AES key — same params as ConfirmPair
            const aesKey = await derivePairKey(pin, upperToken);

            // Decode IV and ciphertext separately
            const iv = base64ToUint8Array(ivB64) as Uint8Array<ArrayBuffer>;
            const ciphertext = base64ToUint8Array(encryptedBundleB64) as Uint8Array<ArrayBuffer>;

            const plainBytes = await crypto.subtle.decrypt(
                { name: 'AES-GCM', iv },
                aesKey,
                ciphertext,
            );

            const plainText = new TextDecoder().decode(plainBytes);
            const bundle = JSON.parse(plainText) as {
                lookup_hash: string;
                user_email_salt: string;
                encrypted_key: string;
                salt: string;
            };

            // Activate restricted pair session state BEFORE dispatching login
            activatePairSession({
                authorizerDeviceName,
                autoLogoutMinutes: returnedAutoLogoutMinutes,
            });

            // Dispatch login event — parent (+page.svelte) performs the actual auth
            dispatch('login', {
                lookupHash: bundle.lookup_hash,
                userEmailSalt: bundle.user_email_salt,
                encryptedKey: bundle.encrypted_key,
                salt: bundle.salt,
                authorizerDeviceName,
                autoLogoutMinutes: returnedAutoLogoutMinutes,
            });
        } catch (err: unknown) {
            console.error('[PairInitiate] Decryption failed:', err);
            pinStatus = 'error';
            pinErrorMessage = $text('settings.sessions.pair_pin_error').replace('{n}', '?');
        }
    }

    /**
     * Derive AES-256-GCM key from PIN + token as salt.
     * PBKDF2-SHA256, 100_000 iterations. Must match SettingsSessionsConfirmPair exactly.
     */
    async function derivePairKey(pin: string, upperToken: string): Promise<CryptoKey> {
        const enc = new TextEncoder();
        const keyMaterial = await crypto.subtle.importKey(
            'raw',
            enc.encode(pin),
            'PBKDF2',
            false,
            ['deriveKey'],
        );
        return crypto.subtle.deriveKey(
            {
                name: 'PBKDF2',
                salt: enc.encode(upperToken),
                iterations: 100_000,
                hash: 'SHA-256',
            },
            keyMaterial,
            { name: 'AES-GCM', length: 256 },
            false,
            ['encrypt', 'decrypt'],
        );
    }

    // ========================================================================
    // UI HELPERS
    // ========================================================================

    async function copyLink() {
        if (!pairUrl) return;
        try {
            await navigator.clipboard.writeText(pairUrl);
            copied = true;
            setTimeout(() => { copied = false; }, 2000);
        } catch {
            // Clipboard not available — silently ignore
        }
    }

    function handlePinInput(e: Event) {
        const target = e.target as HTMLInputElement;
        // Allow only A-Z and 0-9, max 6
        pinValue = target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6);
        target.value = pinValue;
        pinErrorMessage = '';

        if (pairStatus === 'ready' && pinValue.length === 6 && pinStatus !== 'submitting' && pinStatus !== 'locked') {
            void submitPin();
        }
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
        <button class="btn btn-secondary" onclick={initiatePairing}>
            {$text('settings.sessions.pair_refresh')}
        </button>

    {:else if pairStatus === 'expired'}
        <div class="info-box">
            <p>{$text('settings.sessions.pair_expired')}</p>
        </div>
        <button class="btn btn-secondary" onclick={initiatePairing}>
            {$text('settings.sessions.pair_refresh')}
        </button>

    {:else if pairStatus === 'waiting' || pairStatus === 'ready'}
        <p class="scan-label">📷 Scan code:</p>

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
                        ? $text('settings.sessions.pair_copied')
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
        border-radius: 12px;
        overflow: hidden;
        border: 1px solid var(--color-grey-25);
        line-height: 0; /* collapse whitespace around inline SVG */
    }

    .url-section {
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-25);
        border-radius: 10px;
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
        border-radius: 8px;
        padding: 0.75rem 1rem;
        font-size: var(--processing-details-font-size);
        color: var(--color-font-primary);
    }

    .error-box {
        background: rgba(223, 27, 65, 0.08);
        border: 1px solid rgba(223, 27, 65, 0.25);
        border-radius: 8px;
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
        border-radius: 10px;
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
        outline: none;
        border-color: var(--color-primary);
    }

    .pin-input:disabled {
        opacity: 0.6;
    }

    /* Buttons */
    .btn {
        padding: 0.6rem 1.25rem;
        border-radius: 8px;
        font-size: var(--button-font-size);
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition: opacity 0.15s;
    }

    .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .btn-primary {
        background: var(--color-primary);
        color: var(--color-grey-0);
    }

    .btn-primary:hover:not(:disabled) {
        opacity: 0.88;
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
