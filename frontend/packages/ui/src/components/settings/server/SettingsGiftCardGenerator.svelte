<!--
Admin Gift Card Generator - Allows admins to generate one or more gift card codes.
Supports custom prefix (replaces first segment of XXXX-XXXX-XXXX format),
configurable credit value, batch generation, copy signup link, QR code overlay,
and a live list of active (unredeemed) gift cards fetched from the server.

Security: This component is only accessible when the user is admin (enforced by
the 'server/' route prefix in Settings.svelte and the require_admin backend dependency).
-->

<script lang="ts">
    import { getApiEndpoint, text } from '@repo/ui';
    import { notificationStore } from '../../../stores/notificationStore';
    import { focusTrap } from '../../../actions/focusTrap';
    import { fade } from 'svelte/transition';
    import QRCodeSVG from 'qrcode-svg';
    import { onMount } from 'svelte';
    import { copyToClipboard } from '../../../utils/clipboardUtils';

    // --- Constants ---
    const _QR_CODE_SIZE = 200;
    const QR_FULLSCREEN_SIZE = Math.min(600, typeof window !== 'undefined' ? Math.min(window.innerWidth, window.innerHeight) - 40 : 600);
    const COPIED_RESET_MS = 2000;

    // --- Form State ---
    let creditsValue = $state(100);
    let quantity = $state(1);
    let prefix = $state('');
    let notes = $state('');

    // --- UI State ---
    let isGenerating = $state(false);
    let errorMessage = $state('');
    let generatedCodes: Array<{ code: string; credits_value: number; created_at: string }> = $state([]);
    let copiedIndex = $state<number | null>(null);
    let copiedAll = $state(false);

    // --- QR Overlay State ---
    let showQROverlay = $state(false);
    let qrOverlaySvg = $state('');
    let qrOverlayCode = $state('');
    let qrOverlayCredits = $state(0);

    // --- Active Gift Cards State ---
    let activeCards: Array<{ code: string; credits_value: number; created_at: string; notes: string | null }> = $state([]);
    let isLoadingActive = $state(false);
    let activeLoadError = $state('');
    let copiedActiveIndex = $state<number | null>(null);

    // --- Validation ---
    const VALID_PREFIX_CHARS = /^[A-HJ-NP-Z2-9]*$/;

    let prefixError = $derived.by(() => {
        if (!prefix) return '';
        const upper = prefix.toUpperCase();
        if (!VALID_PREFIX_CHARS.test(upper)) {
            return $text('settings.server.gift_cards.invalid_prefix');
        }
        if (upper.length > 4) {
            return $text('settings.server.gift_cards.invalid_prefix');
        }
        return '';
    });

    let codePreview = $derived.by(() => {
        const p = prefix.toUpperCase();
        if (!p || prefixError) {
            return 'XXXX-XXXX-XXXX';
        }
        const remaining = 'X'.repeat(4 - p.length);
        return `${p}${remaining}-XXXX-XXXX`;
    });

    let isFormValid = $derived(
        creditsValue >= 1 && creditsValue <= 50000 &&
        quantity >= 1 && quantity <= 100 &&
        !prefixError
    );

    // --- Helpers ---

    /** Build the signup deep link for a gift card code */
    function buildSignupLink(code: string): string {
        const origin = typeof window !== 'undefined' ? window.location.origin : '';
        return `${origin}/#gift-card=${code}`;
    }

    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    }

    function formatDate(isoDate: string): string {
        try {
            const d = new Date(isoDate);
            return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
        } catch {
            return isoDate;
        }
    }

    /** Generate a QR code SVG string for the given URL */
    function generateQR(url: string, size: number): string {
        try {
            const qr = new QRCodeSVG({
                content: url,
                padding: 4,
                width: size,
                height: size,
                color: '#000000',
                background: '#ffffff',
                ecl: 'M'
            });
            return qr.svg();
        } catch (err) {
            console.error('[SettingsGiftCardGenerator] QR generation error:', err);
            return '';
        }
    }

    // --- Portal action (renders overlay at body root to escape stacking contexts) ---
    function portal(node: HTMLElement) {
        document.body.appendChild(node);
        return {
            destroy() {
                if (node.parentNode) {
                    node.parentNode.removeChild(node);
                }
            }
        };
    }

    // --- QR Overlay ---

    function showQR(code: string, credits: number) {
        const link = buildSignupLink(code);
        qrOverlaySvg = generateQR(link, QR_FULLSCREEN_SIZE);
        qrOverlayCode = code;
        qrOverlayCredits = credits;
        showQROverlay = true;
    }

    function closeQR() {
        showQROverlay = false;
        qrOverlaySvg = '';
        qrOverlayCode = '';
        qrOverlayCredits = 0;
    }

    // --- API: Generate Gift Cards ---

    async function generateGiftCards() {
        if (!isFormValid || isGenerating) return;

        isGenerating = true;
        errorMessage = '';
        generatedCodes = [];
        copiedIndex = null;
        copiedAll = false;

        try {
            const body: Record<string, unknown> = {
                credits_value: creditsValue,
                count: quantity,
            };
            if (prefix.trim()) {
                body.prefix = prefix.trim().toUpperCase();
            }
            if (notes.trim()) {
                body.notes = notes.trim();
            }

            const response = await fetch(getApiEndpoint('/v1/admin/generate-gift-cards'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(body)
            });

            if (!response.ok) {
                const data = await response.json().catch(() => null);
                const detail = data?.detail || `HTTP ${response.status}`;
                throw new Error(detail);
            }

            const data = await response.json();

            if (data.success && data.gift_cards) {
                generatedCodes = data.gift_cards;
                notificationStore.success(
                    `${data.count} gift card${data.count > 1 ? 's' : ''} generated`
                );
                // Refresh active cards list after generating new ones
                fetchActiveCards();
            } else {
                throw new Error(data.message || 'Unknown error');
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to generate gift cards';
            errorMessage = message;
            console.error('[SettingsGiftCardGenerator] Error:', err);
            notificationStore.error(message);
        } finally {
            isGenerating = false;
        }
    }

    // --- API: Fetch Active Gift Cards ---

    async function fetchActiveCards() {
        isLoadingActive = true;
        activeLoadError = '';

        try {
            const response = await fetch(getApiEndpoint('/v1/admin/gift-cards'), {
                method: 'GET',
                credentials: 'include'
            });

            if (!response.ok) {
                const data = await response.json().catch(() => null);
                const detail = data?.detail || `HTTP ${response.status}`;
                throw new Error(detail);
            }

            const data = await response.json();
            activeCards = data.gift_cards || [];
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to load active gift cards';
            activeLoadError = message;
            console.error('[SettingsGiftCardGenerator] Error fetching active cards:', err);
        } finally {
            isLoadingActive = false;
        }
    }

    // --- Clipboard Actions ---

    /** Copy the signup link (not just the raw code) */
    async function copySignupLink(code: string, index: number, isActive: boolean) {
        try {
            const link = buildSignupLink(code);
            const clipResult = await copyToClipboard(link);
            if (!clipResult.success) throw new Error(clipResult.error || 'Copy failed');
            if (isActive) {
                copiedActiveIndex = index;
                setTimeout(() => {
                    if (copiedActiveIndex === index) copiedActiveIndex = null;
                }, COPIED_RESET_MS);
            } else {
                copiedIndex = index;
                setTimeout(() => {
                    if (copiedIndex === index) copiedIndex = null;
                }, COPIED_RESET_MS);
            }
        } catch (err) {
            console.error('[SettingsGiftCardGenerator] Failed to copy:', err);
            notificationStore.error('Failed to copy to clipboard');
        }
    }

    async function copyAllCodes() {
        try {
            const allLinks = generatedCodes.map(c => buildSignupLink(c.code)).join('\n');
            const allClipResult = await copyToClipboard(allLinks);
            if (!allClipResult.success) throw new Error(allClipResult.error || 'Copy failed');
            copiedAll = true;
            notificationStore.success($text('settings.server.gift_cards.copied'));
            setTimeout(() => {
                copiedAll = false;
            }, COPIED_RESET_MS);
        } catch (err) {
            console.error('[SettingsGiftCardGenerator] Failed to copy all:', err);
            notificationStore.error('Failed to copy to clipboard');
        }
    }

    // --- Prefix Input Handler ---
    function handlePrefixInput(event: Event) {
        const input = event.target as HTMLInputElement;
        prefix = input.value.toUpperCase().slice(0, 4);
    }

    // --- Lifecycle ---
    onMount(() => {
        fetchActiveCards();
    });
</script>

<div class="generator-container">
    <!-- Form Section -->
    <div class="form-section">
        <h3 class="section-title">{$text('settings.server.gift_cards.title')}</h3>
        <p class="section-subtitle">{$text('settings.server.gift_cards.subtitle')}</p>

        <!-- Credits Value -->
        <div class="field-group">
            <label class="field-label" for="credits-value">
                {$text('settings.server.gift_cards.credits_value')}
            </label>
            <input
                id="credits-value"
                type="number"
                class="field-input"
                bind:value={creditsValue}
                min="1"
                max="50000"
                placeholder="100"
            />
            <span class="field-hint">1 - 50,000</span>
        </div>

        <!-- Quantity -->
        <div class="field-group">
            <label class="field-label" for="quantity">
                {$text('settings.server.gift_cards.quantity')}
            </label>
            <input
                id="quantity"
                type="number"
                class="field-input"
                bind:value={quantity}
                min="1"
                max="100"
                placeholder="1"
            />
            <span class="field-hint">1 - 100</span>
        </div>

        <!-- Custom Prefix -->
        <div class="field-group">
            <label class="field-label" for="prefix">
                {$text('settings.server.gift_cards.prefix')}
                <span class="optional-label">({$text('settings.server.gift_cards.optional')})</span>
            </label>
            <input
                id="prefix"
                type="text"
                class="field-input prefix-input"
                value={prefix}
                oninput={handlePrefixInput}
                maxlength="4"
                placeholder={$text('settings.server.gift_cards.prefix_placeholder')}
                autocomplete="off"
                spellcheck="false"
            />
            {#if prefixError}
                <span class="field-error">{prefixError}</span>
            {:else}
                <span class="field-hint preview-hint">
                    {$text('settings.server.gift_cards.prefix_preview')}: <span class="code-preview">{codePreview}</span>
                </span>
            {/if}
        </div>

        <!-- Notes -->
        <div class="field-group">
            <label class="field-label" for="notes">
                {$text('settings.server.gift_cards.notes')}
                <span class="optional-label">({$text('settings.server.gift_cards.optional')})</span>
            </label>
            <input
                id="notes"
                type="text"
                class="field-input"
                bind:value={notes}
                maxlength="500"
                placeholder={$text('settings.server.gift_cards.notes_placeholder')}
            />
        </div>

        <!-- Generate Button -->
        <button
            class="btn-generate"
            onclick={generateGiftCards}
            disabled={!isFormValid || isGenerating}
        >
            {#if isGenerating}
                {$text('settings.server.gift_cards.generating')}
            {:else}
                {$text('settings.server.gift_cards.generate')}
            {/if}
        </button>

        {#if errorMessage}
            <div class="error-message">{errorMessage}</div>
        {/if}
    </div>

    <!-- Generated Codes Results Section -->
    {#if generatedCodes.length > 0}
        <div class="results-section">
            <div class="results-header">
                <h3 class="results-title">
                    {$text('settings.server.gift_cards.generated_codes')}
                    <span class="results-count">({generatedCodes.length})</span>
                </h3>
                {#if generatedCodes.length > 1}
                    <button
                        class="btn-copy-all"
                        onclick={copyAllCodes}
                    >
                        {#if copiedAll}
                            <span class="copied-icon"></span>
                            {$text('settings.server.gift_cards.copied')}
                        {:else}
                            <span class="copy-icon"></span>
                            {$text('settings.server.gift_cards.copy_all')}
                        {/if}
                    </button>
                {/if}
            </div>

            <div class="codes-list">
                {#each generatedCodes as card, index}
                    <div class="code-item">
                        <div class="code-info">
                            <span class="code-text">{card.code}</span>
                            <span class="code-credits">{formatCredits(card.credits_value)} credits</span>
                        </div>
                        <div class="code-actions">
                            <button
                                class="btn-icon"
                                onclick={() => showQR(card.code, card.credits_value)}
                                title={$text('settings.server.gift_cards.show_qr')}
                            >
                                <span class="qr-icon"></span>
                            </button>
                            <button
                                class="btn-icon"
                                onclick={() => copySignupLink(card.code, index, false)}
                                title={$text('settings.server.gift_cards.copy_link')}
                            >
                                {#if copiedIndex === index}
                                    <span class="copied-icon"></span>
                                {:else}
                                    <span class="copy-icon"></span>
                                {/if}
                            </button>
                        </div>
                    </div>
                {/each}
            </div>
        </div>
    {/if}

    <!-- Active Gift Cards Section -->
    <div class="active-section">
        <div class="active-header">
            <h3 class="section-title">{$text('settings.server.gift_cards.active_cards')}</h3>
            <button
                class="btn-refresh"
                onclick={fetchActiveCards}
                disabled={isLoadingActive}
                title={$text('settings.server.gift_cards.active_cards_refresh')}
            >
                <span class="refresh-icon" class:spinning={isLoadingActive}></span>
            </button>
        </div>

        {#if isLoadingActive && activeCards.length === 0}
            <p class="active-status">{$text('settings.server.gift_cards.loading_cards')}</p>
        {:else if activeLoadError}
            <p class="active-status error">{$text('settings.server.gift_cards.load_error')}</p>
        {:else if activeCards.length === 0}
            <p class="active-status">{$text('settings.server.gift_cards.active_cards_empty')}</p>
        {:else}
            <div class="codes-list">
                {#each activeCards as card, index}
                    <div class="code-item">
                        <div class="code-info">
                            <span class="code-text">{card.code}</span>
                            <span class="code-credits">
                                {formatCredits(card.credits_value)} credits
                                {#if card.notes}
                                    &middot; {card.notes}
                                {/if}
                            </span>
                            <span class="code-date">{$text('settings.server.gift_cards.created_at')}: {formatDate(card.created_at)}</span>
                        </div>
                        <div class="code-actions">
                            <button
                                class="btn-icon"
                                onclick={() => showQR(card.code, card.credits_value)}
                                title={$text('settings.server.gift_cards.show_qr')}
                            >
                                <span class="qr-icon"></span>
                            </button>
                            <button
                                class="btn-icon"
                                onclick={() => copySignupLink(card.code, index, true)}
                                title={$text('settings.server.gift_cards.copy_link')}
                            >
                                {#if copiedActiveIndex === index}
                                    <span class="copied-icon"></span>
                                {:else}
                                    <span class="copy-icon"></span>
                                {/if}
                            </button>
                        </div>
                    </div>
                {/each}
            </div>
        {/if}
    </div>
</div>

<!-- QR Code Fullscreen Overlay (portaled to body) -->
{#if showQROverlay && qrOverlaySvg}
    <div
        class="qr-fullscreen-overlay"
        use:portal
        role="dialog"
        aria-modal="true"
        aria-label="QR Code"
        use:focusTrap={{ onEscape: closeQR }}
        onmousedown={(e) => { if (e.target === e.currentTarget) closeQR(); }}
        tabindex="-1"
        transition:fade={{ duration: 200 }}
    >
        <div class="qr-fullscreen-card">
            <div class="qr-fullscreen-header">
                <span class="qr-fullscreen-code">{qrOverlayCode}</span>
                <span class="qr-fullscreen-credits">{formatCredits(qrOverlayCredits)} credits</span>
            </div>
            <div class="qr-fullscreen-svg">
                {@html qrOverlaySvg}
            </div>
            <p class="qr-fullscreen-hint">{$text('settings.server.gift_cards.qr_code_hint')}</p>
            <button class="qr-fullscreen-close" onclick={closeQR}>
                {$text('settings.server.gift_cards.close')}
            </button>
        </div>
    </div>
{/if}

<style>
    .generator-container {
        display: flex;
        flex-direction: column;
        gap: 24px;
        padding: 0 4px;
    }

    /* Form Section */
    .form-section {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .section-title {
        font-size: 18px;
        font-weight: 600;
        color: var(--color-grey-100);
        margin: 0;
    }

    .section-subtitle {
        font-size: 14px;
        color: var(--color-grey-60);
        margin: 0;
        margin-top: -8px;
    }

    /* Field Groups */
    .field-group {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .field-label {
        font-size: 13px;
        font-weight: 500;
        color: var(--color-grey-80);
    }

    .optional-label {
        font-weight: 400;
        color: var(--color-grey-50);
        font-size: 12px;
    }

    .field-input {
        width: 100%;
        max-width: 350px;
        padding: 10px 14px;
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        background: var(--color-grey-10);
        color: var(--color-grey-100);
        font-size: 14px;
        transition: border-color 0.15s ease;
        box-sizing: border-box;
    }

    .field-input:focus {
        border-color: var(--accent-color, var(--color-grey-50));
    }

    .field-input::placeholder {
        color: var(--color-grey-40);
    }

    .prefix-input {
        text-transform: uppercase;
        font-family: 'Courier New', monospace;
        letter-spacing: 2px;
        font-weight: 600;
    }

    .field-hint {
        font-size: 12px;
        color: var(--color-grey-50);
    }

    .field-error {
        font-size: 12px;
        color: #dc2626;
    }

    .preview-hint {
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .code-preview {
        font-family: 'Courier New', monospace;
        font-weight: 600;
        letter-spacing: 1px;
        color: var(--color-grey-70);
    }

    /* Generate Button */
    .btn-generate {
        max-width: 350px;
        padding: 12px 20px;
        border: none;
        border-radius: 8px;
        background: var(--accent-color);
        color: white;
        font-size: 15px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.15s ease;
        margin-top: 4px;
    }

    .btn-generate:hover:not(:disabled) {
        opacity: 0.9;
        scale: 1.01;
    }

    .btn-generate:active:not(:disabled) {
        scale: 0.99;
    }

    .btn-generate:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .error-message {
        font-size: 13px;
        color: #dc2626;
        padding: 8px 12px;
        background: rgba(220, 38, 38, 0.08);
        border-radius: 6px;
        max-width: 350px;
    }

    /* Results / Active Section */
    .results-section,
    .active-section {
        display: flex;
        flex-direction: column;
        gap: 12px;
        border-top: 1px solid var(--color-grey-20);
        padding-top: 20px;
    }

    .results-header,
    .active-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    }

    .results-title {
        font-size: 15px;
        font-weight: 600;
        color: var(--color-grey-100);
        margin: 0;
    }

    .results-count {
        font-weight: 400;
        color: var(--color-grey-50);
    }

    .btn-copy-all {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px;
        border: 1px solid var(--color-grey-30);
        border-radius: 6px;
        background: var(--color-grey-10);
        color: var(--color-grey-80);
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.15s ease;
        white-space: nowrap;
        flex-shrink: 0;
    }

    .btn-copy-all:hover {
        background: var(--color-grey-20);
        border-color: var(--color-grey-40);
    }

    /* Codes List */
    .codes-list {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .code-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 14px;
        background: var(--color-grey-10);
        border-radius: 8px;
        border: 1px solid var(--color-grey-20);
        transition: border-color 0.15s ease;
    }

    .code-item:hover {
        border-color: var(--color-grey-30);
    }

    .code-info {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
    }

    .code-text {
        font-family: 'Courier New', monospace;
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 1.5px;
        color: var(--color-grey-100);
    }

    .code-credits {
        font-size: 12px;
        color: var(--color-grey-50);
    }

    .code-date {
        font-size: 11px;
        color: var(--color-grey-40);
    }

    .code-actions {
        display: flex;
        align-items: center;
        gap: 4px;
        flex-shrink: 0;
    }

    /* Icon Buttons (QR, Copy) */
    .btn-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        border: none;
        border-radius: 6px;
        background: transparent;
        cursor: pointer;
        transition: background 0.15s ease;
        flex-shrink: 0;
    }

    .btn-icon:hover {
        background: var(--color-grey-20);
    }

    /* Refresh Button */
    .btn-refresh {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        border: 1px solid var(--color-grey-30);
        border-radius: 6px;
        background: var(--color-grey-10);
        cursor: pointer;
        transition: all 0.15s ease;
        flex-shrink: 0;
    }

    .btn-refresh:hover:not(:disabled) {
        background: var(--color-grey-20);
        border-color: var(--color-grey-40);
    }

    .btn-refresh:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .refresh-icon {
        display: inline-block;
        width: 14px;
        height: 14px;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2'/%3E%3C/svg%3E");
        background-size: contain;
        background-repeat: no-repeat;
        transition: transform 0.3s ease;
    }

    .refresh-icon.spinning {
        animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }

    .active-status {
        font-size: 13px;
        color: var(--color-grey-50);
        margin: 0;
        padding: 8px 0;
    }

    .active-status.error {
        color: #dc2626;
    }

    /* Copy/Copied/QR Icons */
    .copy-icon,
    .copied-icon,
    .qr-icon {
        display: inline-block;
        width: 16px;
        height: 16px;
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
    }

    .copy-icon {
        background-image: url('@openmates/ui/static/icons/copy.svg');
        opacity: 0.6;
    }

    .copied-icon {
        background-image: url('@openmates/ui/static/icons/check.svg');
        opacity: 0.8;
    }

    .qr-icon {
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3' y='3' width='7' height='7'/%3E%3Crect x='14' y='3' width='7' height='7'/%3E%3Crect x='3' y='14' width='7' height='7'/%3E%3Cpath d='M14 14h3v3h-3zM20 14v3h-3M14 20h3M20 20h-3v-3'/%3E%3C/svg%3E");
        opacity: 0.6;
    }

    :global([data-theme="dark"]) .copy-icon,
    :global([data-theme="dark"]) .copied-icon,
    :global([data-theme="dark"]) .qr-icon,
    :global([data-theme="dark"]) .refresh-icon {
        filter: invert(1);
    }

    /* QR Fullscreen Overlay */
    .qr-fullscreen-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: rgba(0, 0, 0, 0.7);
        z-index: 10000;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 20px;
        box-sizing: border-box;
        cursor: pointer;
    }

    .qr-fullscreen-card {
        background: white;
        border-radius: 16px;
        padding: 32px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        max-width: 90vw;
        max-height: 90vh;
        cursor: default;
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
    }

    .qr-fullscreen-header {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
    }

    .qr-fullscreen-code {
        font-family: 'Courier New', monospace;
        font-size: 22px;
        font-weight: 700;
        letter-spacing: 2px;
        color: #1a1a1a;
    }

    .qr-fullscreen-credits {
        font-size: 14px;
        color: #666;
    }

    .qr-fullscreen-svg {
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .qr-fullscreen-svg :global(svg) {
        display: block;
    }

    .qr-fullscreen-hint {
        font-size: 13px;
        color: #888;
        text-align: center;
        margin: 0;
    }

    .qr-fullscreen-close {
        padding: 8px 24px;
        border: 1px solid #ccc;
        border-radius: 8px;
        background: #f5f5f5;
        color: #333;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.15s ease;
    }

    .qr-fullscreen-close:hover {
        background: #eee;
        border-color: #bbb;
    }
</style>
