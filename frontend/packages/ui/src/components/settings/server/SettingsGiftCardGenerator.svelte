<!--
Admin Gift Card Generator - Allows admins to generate one or more gift card codes.
Supports custom prefix (replaces first segment of XXXX-XXXX-XXXX format),
configurable credit value, batch generation, and easy clipboard copy.

Security: This component is only accessible when the user is admin (enforced by
the 'server/' route prefix in Settings.svelte and the require_admin backend dependency).
-->

<script lang="ts">
    import { getApiEndpoint, text } from '@repo/ui';
    import { notificationStore } from '../../../stores/notificationStore';

    // --- Form State ---
    let creditsValue = $state(100);
    let quantity = $state(1);
    let prefix = $state('');
    let notes = $state('');

    // --- UI State ---
    let isGenerating = $state(false);
    let errorMessage = $state('');
    let generatedCodes: Array<{ code: string; credits_value: number; created_at: string }> = $state([]);
    let copiedIndex = $state<number | null>(null); // Track which individual code was just copied
    let copiedAll = $state(false); // Track if "copy all" was just clicked

    // --- Validation ---
    // Valid charset matches backend: A-Z (minus O,I) + 0-9 (minus 0,1)
    const VALID_PREFIX_CHARS = /^[A-HJ-NP-Z2-9]*$/;

    let prefixError = $derived.by(() => {
        if (!prefix) return '';
        const upper = prefix.toUpperCase();
        if (!VALID_PREFIX_CHARS.test(upper)) {
            return $text('settings.server.gift_cards.invalid_prefix.text');
        }
        if (upper.length > 4) {
            return $text('settings.server.gift_cards.invalid_prefix.text');
        }
        return '';
    });

    // Preview of what the code format will look like
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

    // --- API Call ---
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

    // --- Clipboard Actions ---
    async function copySingleCode(code: string, index: number) {
        try {
            await navigator.clipboard.writeText(code);
            copiedIndex = index;
            // Reset copied state after 2 seconds
            setTimeout(() => {
                if (copiedIndex === index) copiedIndex = null;
            }, 2000);
        } catch (err) {
            console.error('[SettingsGiftCardGenerator] Failed to copy:', err);
            notificationStore.error('Failed to copy to clipboard');
        }
    }

    async function copyAllCodes() {
        try {
            const allCodes = generatedCodes.map(c => c.code).join('\n');
            await navigator.clipboard.writeText(allCodes);
            copiedAll = true;
            notificationStore.success($text('settings.server.gift_cards.copied.text'));
            // Reset copied state after 2 seconds
            setTimeout(() => {
                copiedAll = false;
            }, 2000);
        } catch (err) {
            console.error('[SettingsGiftCardGenerator] Failed to copy all:', err);
            notificationStore.error('Failed to copy to clipboard');
        }
    }

    // --- Credits Formatting ---
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    }

    // --- Prefix Input Handler ---
    function handlePrefixInput(event: Event) {
        const input = event.target as HTMLInputElement;
        // Auto-uppercase and limit to 4 chars
        prefix = input.value.toUpperCase().slice(0, 4);
    }
</script>

<div class="generator-container">
    <!-- Form Section -->
    <div class="form-section">
        <h3 class="section-title">{$text('settings.server.gift_cards.title.text')}</h3>
        <p class="section-subtitle">{$text('settings.server.gift_cards.subtitle.text')}</p>

        <!-- Credits Value -->
        <div class="field-group">
            <label class="field-label" for="credits-value">
                {$text('settings.server.gift_cards.credits_value.text')}
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
                {$text('settings.server.gift_cards.quantity.text')}
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
                {$text('settings.server.gift_cards.prefix.text')}
                <span class="optional-label">({$text('settings.server.gift_cards.optional.text')})</span>
            </label>
            <input
                id="prefix"
                type="text"
                class="field-input prefix-input"
                value={prefix}
                oninput={handlePrefixInput}
                maxlength="4"
                placeholder={$text('settings.server.gift_cards.prefix_placeholder.text')}
                autocomplete="off"
                spellcheck="false"
            />
            {#if prefixError}
                <span class="field-error">{prefixError}</span>
            {:else}
                <span class="field-hint preview-hint">
                    {$text('settings.server.gift_cards.prefix_preview.text')}: <span class="code-preview">{codePreview}</span>
                </span>
            {/if}
        </div>

        <!-- Notes -->
        <div class="field-group">
            <label class="field-label" for="notes">
                {$text('settings.server.gift_cards.notes.text')}
                <span class="optional-label">({$text('settings.server.gift_cards.optional.text')})</span>
            </label>
            <input
                id="notes"
                type="text"
                class="field-input"
                bind:value={notes}
                maxlength="500"
                placeholder={$text('settings.server.gift_cards.notes_placeholder.text')}
            />
        </div>

        <!-- Generate Button -->
        <button
            class="btn-generate"
            onclick={generateGiftCards}
            disabled={!isFormValid || isGenerating}
        >
            {#if isGenerating}
                {$text('settings.server.gift_cards.generating.text')}
            {:else}
                {$text('settings.server.gift_cards.generate.text')}
            {/if}
        </button>

        {#if errorMessage}
            <div class="error-message">{errorMessage}</div>
        {/if}
    </div>

    <!-- Results Section -->
    {#if generatedCodes.length > 0}
        <div class="results-section">
            <div class="results-header">
                <h3 class="results-title">
                    {$text('settings.server.gift_cards.generated_codes.text')}
                    <span class="results-count">({generatedCodes.length})</span>
                </h3>
                {#if generatedCodes.length > 1}
                    <button
                        class="btn-copy-all"
                        onclick={copyAllCodes}
                    >
                        {#if copiedAll}
                            <span class="copied-icon"></span>
                            {$text('settings.server.gift_cards.copied.text')}
                        {:else}
                            <span class="copy-icon"></span>
                            {$text('settings.server.gift_cards.copy_all.text')}
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
                        <button
                            class="btn-copy-code"
                            onclick={() => copySingleCode(card.code, index)}
                            title={$text('settings.server.gift_cards.copy_code.text')}
                        >
                            {#if copiedIndex === index}
                                <span class="copied-icon"></span>
                            {:else}
                                <span class="copy-icon"></span>
                            {/if}
                        </button>
                    </div>
                {/each}
            </div>
        </div>
    {/if}
</div>

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
        outline: none;
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

    /* Results Section */
    .results-section {
        display: flex;
        flex-direction: column;
        gap: 12px;
        border-top: 1px solid var(--color-grey-20);
        padding-top: 20px;
    }

    .results-header {
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

    .btn-copy-code {
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

    .btn-copy-code:hover {
        background: var(--color-grey-20);
    }

    /* Copy/Copied Icons */
    .copy-icon,
    .copied-icon {
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

    /* Dark mode adjustments for icons */
    :global([data-theme="dark"]) .copy-icon,
    :global([data-theme="dark"]) .copied-icon {
        filter: invert(1);
    }
</style>
