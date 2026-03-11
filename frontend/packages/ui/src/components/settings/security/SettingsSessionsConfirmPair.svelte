<!--
SettingsSessionsConfirmPair — Authorizing device UI for magic pair login.

The already-logged-in device opens this page (via /#pair=TOKEN deep link) to:
  1. See the requesting device's info (name, truncated IP, location)
  2. Choose an auto-logout duration for the new session
  3. Allow or Deny
  4. On Allow: display a 6-digit PIN to the user, who relays it to the new device

Architecture: docs/architecture/device-sessions.md
Zero-knowledge: the server stores the plaintext PIN only for /complete validation
(never decrypts the bundle). The bundle itself is AES-256-GCM encrypted with a
key derived from PIN + token-as-salt (PBKDF2 / 100k iterations).
-->

<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint } from '../../../config/api';
    import { uint8ArrayToBase64 } from '../../../services/cryptoService';
    import { get } from 'svelte/store';
    import { pendingPairToken } from '../../../stores/pairSessionStore';

    const dispatch = createEventDispatcher<{ denied: void; done: void }>();

    // ========================================================================
    // STATE
    // ========================================================================

    // Token is passed via pendingPairToken store (set by the onPair deep link handler
    // in +page.svelte before navigating to this route). Consumed once on mount and
    // cleared so a back-navigation doesn't re-use a stale token.
    let token = $state<string>('');

    // ========================================================================
    // TYPES
    // ========================================================================

    interface RequestingDeviceInfo {
        device_name: string;
        ip_truncated: string;
        country_code: string | null;
        city: string | null;
    }

    type PageStatus = 'loading' | 'confirm' | 'authorizing' | 'pin_display' | 'denied' | 'error' | 'invalid';

    // ========================================================================
    // COMPONENT STATE
    // ========================================================================

    let pageStatus = $state<PageStatus>('loading');
    let deviceInfo = $state<RequestingDeviceInfo | null>(null);
    let errorMessage = $state('');
    let generatedPin = $state<string | null>(null);
    let autoLogoutMinutes = $state<number | null>(null);

    // ========================================================================
    // LIFECYCLE
    // ========================================================================

    onMount(async () => {
        // Consume the pending token from the store (set by the onPair deep link handler).
        const storedToken = get(pendingPairToken);
        pendingPairToken.set(null); // Clear immediately so stale token isn't re-used on back-nav
        if (!storedToken) {
            pageStatus = 'invalid';
            return;
        }
        token = storedToken;
        await loadDeviceInfo();
    });

    // ========================================================================
    // DATA FETCHING
    // ========================================================================

    async function loadDeviceInfo() {
        pageStatus = 'loading';
        errorMessage = '';
        try {
            const response = await fetch(getApiEndpoint(`/v1/auth/pair/info/${token}`), {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
            });

            const data = await response.json().catch(() => ({}));

            if (!response.ok || data.valid === false) {
                pageStatus = 'invalid';
                return;
            }

            deviceInfo = {
                device_name: data.device_name || 'Unknown device',
                ip_truncated: data.ip_truncated || '',
                country_code: data.country_code || null,
                city: data.city || null,
            };
            pageStatus = 'confirm';
        } catch (err: unknown) {
            console.error('[ConfirmPair] Failed to load device info:', err);
            errorMessage = err instanceof Error ? err.message : 'Failed to load request';
            pageStatus = 'error';
        }
    }

    // ========================================================================
    // ACTIONS
    // ========================================================================

    async function allow() {
        if (!deviceInfo) return;
        pageStatus = 'authorizing';
        errorMessage = '';

        try {
            // 1. Generate a random 6-digit PIN
            const pin = generatePin();
            generatedPin = pin;

            // 2. Derive AES-256 key from PIN + token-as-salt (PBKDF2, 100k iterations / SHA-256)
            //    Must match the same derivation the initiating device will use to decrypt.
            const upperToken = token.toUpperCase();
            const aesKey = await derivePairKey(pin, upperToken);

            // 3. Build the plaintext bundle from the current user's stored auth material
            const bundle = await buildBundle();

            // 4. Encrypt the bundle with AES-256-GCM
            const iv = crypto.getRandomValues(new Uint8Array(12));
            const plainBytes = new TextEncoder().encode(JSON.stringify(bundle));
            const cipherBytes = await crypto.subtle.encrypt(
                { name: 'AES-GCM', iv },
                aesKey,
                plainBytes,
            );

            const encryptedBundleB64 = uint8ArrayToBase64(new Uint8Array(cipherBytes));
            const ivB64 = uint8ArrayToBase64(iv);

            // 5. POST to authorize endpoint
            //    - encrypted_bundle: ciphertext (base64)
            //    - iv: 12-byte IV (base64, stored separately)
            //    - pin: plaintext — server stores for /complete brute-force guard
            //    - authorizer_device_name: shown on initiating device
            const authorizerName = getAuthorizerDeviceName();

            const response = await fetch(getApiEndpoint(`/v1/auth/pair/authorize/${token}`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    encrypted_bundle: encryptedBundleB64,
                    iv: ivB64,
                    pin,
                    authorizer_device_name: authorizerName,
                }),
            });

            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.detail || 'Authorization failed');
            }

            pageStatus = 'pin_display';
        } catch (err: unknown) {
            console.error('[ConfirmPair] Authorization failed:', err);
            errorMessage = err instanceof Error ? err.message : $text('settings.sessions.pair_confirm_error');
            pageStatus = 'error';
        }
    }

    async function deny() {
        pageStatus = 'denied';
        dispatch('denied');
    }

    // ========================================================================
    // CRYPTO HELPERS
    // ========================================================================

    /** Generate a cryptographically random 6-digit PIN (000000–999999) */
    function generatePin(): string {
        const arr = new Uint32Array(1);
        crypto.getRandomValues(arr);
        return String(arr[0] % 1_000_000).padStart(6, '0');
    }

    /**
     * Derive AES-256-GCM key from PIN + token as salt.
     * PBKDF2-SHA256, 100_000 iterations.
     * The initiating device uses the same derivation to decrypt the bundle.
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

    /**
     * Build the plaintext bundle that the initiating device needs to log in.
     *
     * The bundle holds the credentials needed to call POST /auth/login:
     *   lookup_hash  — hashed credential passed to /auth/login
     *   user_email_salt — email salt stored in sessionStorage/localStorage
     *   encrypted_key — server-side encrypted master key (from login response)
     *   salt          — key derivation salt
     *
     * These are read from sessionStorage where they were stored during login.
     * They are never sent to the server in plaintext — only as AES ciphertext.
     */
    async function buildBundle(): Promise<{
        lookup_hash: string;
        user_email_salt: string;
        encrypted_key: string;
        salt: string;
    }> {
        // Read credentials persisted during login from sessionStorage.
        // Keys defined in cryptoService.ts and authLoginLogoutActions.ts.
        const lookup_hash = sessionStorage.getItem('openmates_pair_lookup_hash');
        const user_email_salt = sessionStorage.getItem('openmates_email_salt')
            || localStorage.getItem('openmates_email_salt');
        const encrypted_key = sessionStorage.getItem('openmates_pair_encrypted_key');
        const salt = sessionStorage.getItem('openmates_pair_salt');

        if (!lookup_hash || !user_email_salt || !encrypted_key || !salt) {
            // Credentials not found — user may need to log out and back in for pair login to work.
            // This will happen until we wire up the credential storage in the login flow.
            throw new Error(
                'Pair login credentials not available. Please log out and log back in, then try again.'
            );
        }

        return { lookup_hash, user_email_salt, encrypted_key, salt };
    }

    /** Get a human-readable name for this device (the authorizer) */
    function getAuthorizerDeviceName(): string {
        try {
            const ua = navigator.userAgent;
            // Very simple device name extraction
            if (/iPhone/.test(ua)) return 'iPhone';
            if (/iPad/.test(ua)) return 'iPad';
            if (/Android/.test(ua)) return 'Android device';
            if (/Mac/.test(ua)) return 'Mac';
            if (/Windows/.test(ua)) return 'Windows PC';
            if (/Linux/.test(ua)) return 'Linux PC';
            return 'Desktop';
        } catch {
            return 'Desktop';
        }
    }

    // ========================================================================
    // UI HELPERS
    // ========================================================================

    /** Format a country code + city into a location string */
    function formatLocation(info: RequestingDeviceInfo): string {
        const parts: string[] = [];
        if (info.city) parts.push(info.city);
        if (info.country_code) {
            try {
                const names = new Intl.DisplayNames(['en'], { type: 'region' });
                const name = names.of(info.country_code.toUpperCase());
                if (name) parts.push(name);
            } catch {
                parts.push(info.country_code);
            }
        }
        if (info.ip_truncated) parts.push(info.ip_truncated);
        return parts.join(' · ') || 'Unknown location';
    }

    /** Format 6-digit PIN as "123 456" for readability */
    let displayPin = $derived(
        generatedPin ? `${generatedPin.slice(0, 3)} ${generatedPin.slice(3)}` : ''
    );
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
            <button class="btn btn-allow" onclick={() => allow()}>
                {$text('settings.sessions.pair_confirm_allow')}
            </button>
        </div>

    {:else if pageStatus === 'authorizing'}
        <p class="status-text">{$text('settings.sessions.pair_confirm_allowing')}</p>

    {:else if pageStatus === 'pin_display' && generatedPin}
        <h2 class="page-title">{$text('settings.sessions.pair_confirm_show_pin')}</h2>
        <p class="page-description">{$text('settings.sessions.pair_confirm_pin_hint')}</p>

        <div class="pin-display">
            {displayPin}
        </div>

        <button class="btn btn-secondary" onclick={() => dispatch('done')}>
            Done
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
        border-radius: 12px;
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
        border-radius: 8px;
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

    .pin-display {
        font-size: 2.5rem;
        font-weight: 700;
        letter-spacing: 0.25em;
        color: var(--color-font-primary);
        font-variant-numeric: tabular-nums;
        font-family: monospace;
        text-align: center;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-25);
        border-radius: 12px;
        padding: 1.25rem;
    }

    .error-box {
        background: rgba(223, 27, 65, 0.08);
        border: 1px solid rgba(223, 27, 65, 0.25);
        border-radius: 8px;
        padding: 0.75rem 1rem;
        font-size: var(--processing-details-font-size);
        color: var(--color-error);
    }

    .info-box {
        background: rgba(59, 130, 246, 0.07);
        border: 1px solid rgba(59, 130, 246, 0.25);
        border-radius: 8px;
        padding: 0.75rem 1rem;
        font-size: var(--processing-details-font-size);
        color: var(--color-font-primary);
    }

    .btn {
        padding: 0.65rem 1.25rem;
        border-radius: 8px;
        font-size: var(--button-font-size);
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition: opacity 0.15s;
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
