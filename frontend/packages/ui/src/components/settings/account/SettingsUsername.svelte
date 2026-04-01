<!--
    Username Settings — lets the user change their display username.

    Rules (mirrored from backend validate_username):
      - 3–20 characters
      - At least one letter
      - Only letters (including international), numbers, dots (.) and underscores (_)

    Flow:
      1. Pre-fill input with the current username from the userProfile store.
      2. Client-side validation gives instant feedback while the user types.
      3. On save, POST /v1/settings/user/username with { username }.
      4. On success, update the userProfile store + IndexedDB via updateUsername().
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { SettingsSectionHeading } from '../../settings/elements';
    import { getApiUrl, getApiEndpoint, apiEndpoints } from '../../../config/api';
    import { userProfile, updateUsername } from '../../../stores/userProfile';
    import SettingsInput from '../../settings/elements/SettingsInput.svelte';

    // ─── State ────────────────────────────────────────────────────────────────

    let currentUsername = $state<string>('');
    let inputValue = $state<string>('');
    let isSaving = $state(false);
    let errorMessage = $state<string | null>(null);
    let successMessage = $state<string | null>(null);

    // Server-side uniqueness check state
    let usernameAlreadyTaken = $state(false);
    let isCheckingAvailability = $state(false);

    // Whether the input value differs from the saved username
    let hasChanges = $derived(inputValue.trim() !== currentUsername);

    // ─── Validation (same rules as backend validate_username) ─────────────────

    /**
     * Validate the candidate username on the client side before submitting.
     * Returns null if valid, or an i18n key describing the error.
     */
    function validateInput(value: string): string | null {
        const trimmed = value.trim();
        if (trimmed.length < 3 || trimmed.length > 20) {
            return $text('settings.account.username.error_length');
        }
        // Must contain at least one letter (basic Unicode letter detection)
        if (!/\p{L}/u.test(trimmed)) {
            return $text('settings.account.username.error_no_letter');
        }
        // Allowed: letters, numbers, dots, underscores
        if (!/^[\p{L}\p{M}0-9._]+$/u.test(trimmed)) {
            return $text('settings.account.username.error_invalid_chars');
        }
        return null;
    }

    // Derived validation message — shown while typing (only after first blur).
    // Also shows "taken" error when server confirms the username is unavailable.
    let hasBlurred = $state(false);
    let validationError = $derived(
        usernameAlreadyTaken
            ? $text('settings.account.username.error_taken')
            : (hasBlurred ? validateInput(inputValue) : null)
    );

    // ─── Debounced availability check ─────────────────────────────────────────

    /** Generic debounce helper */
    function debounce<T extends (...args: unknown[]) => void>(
        fn: T,
        delay: number
    ): (...args: Parameters<T>) => void {
        let timeoutId: ReturnType<typeof setTimeout>;
        return (...args: Parameters<T>) => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => fn(...args), delay);
        };
    }

    /**
     * Checks whether the typed username is already taken by another account.
     * Only called when format validation passes; skipped when the user is
     * keeping their current username (no need to check against yourself —
     * the backend also handles this via exclude_user_id, but we save the
     * round-trip when the value hasn't changed).
     */
    const debouncedCheckAvailability = debounce(async (value: string) => {
        // Skip network call when user hasn't actually changed the username
        if (value === currentUsername) {
            isCheckingAvailability = false;
            return;
        }

        try {
            const response = await fetch(
                getApiEndpoint(apiEndpoints.auth.check_username_valid),
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                    },
                    body: JSON.stringify({ username: value }),
                    credentials: 'include',
                }
            );

            if (!response.ok) {
                // Server error — fail open (don't block the user)
                console.warn('[SettingsUsername] Availability check HTTP error:', response.status);
                return;
            }

            const data = await response.json();
            usernameAlreadyTaken = !data.available;
        } catch (err) {
            console.warn('[SettingsUsername] Availability check network error:', err);
            // Network error — fail open
        } finally {
            isCheckingAvailability = false;
        }
    }, 600);

    // Trigger availability check whenever inputValue changes (after format passes)
    $effect(() => {
        const trimmed = inputValue.trim();

        // Reset on every keystroke
        usernameAlreadyTaken = false;

        // Only hit the network when format is already valid and value has changed
        if (trimmed && !validateInput(trimmed) && trimmed !== currentUsername) {
            isCheckingAvailability = true;
            debouncedCheckAvailability(trimmed);
        } else {
            isCheckingAvailability = false;
        }
    });

    // ─── Save handler ─────────────────────────────────────────────────────────

    async function handleSave() {
        errorMessage = null;
        successMessage = null;

        const trimmed = inputValue.trim();

        // Final client-side check before sending
        const clientError = validateInput(trimmed);
        if (clientError) {
            errorMessage = clientError;
            return;
        }

        // Guard against a race where the debounced check hasn't resolved yet
        if (usernameAlreadyTaken) {
            errorMessage = $text('settings.account.username.error_taken');
            return;
        }

        isSaving = true;

        try {
            const response = await fetch(getApiUrl() + apiEndpoints.settings.user.username, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                body: JSON.stringify({ username: trimmed }),
                credentials: 'include',
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || $text('settings.account.username.error_failed'));
            }

            // Update Svelte store + IndexedDB so changes are reflected immediately
            // everywhere in the UI (e.g. the settings header).
            await updateUsername(trimmed);

            currentUsername = trimmed;
            inputValue = trimmed;
            hasBlurred = false;

            successMessage = $text('settings.account.username.success');

            // Auto-dismiss the success notice after 3 s
            setTimeout(() => {
                successMessage = null;
            }, 3000);

        } catch (err) {
            console.error('[SettingsUsername] Save failed:', err);
            errorMessage = err instanceof Error
                ? err.message
                : $text('settings.account.username.error_failed');
        } finally {
            isSaving = false;
        }
    }

    // ─── Lifecycle ────────────────────────────────────────────────────────────

    onMount(() => {
        // Pre-fill from the store (already loaded from IndexedDB by the time settings open)
        currentUsername = $userProfile.username || '';
        inputValue = currentUsername;
    });
</script>

<!-- ─── Template ──────────────────────────────────────────────────────────── -->

<div class="settings-username">

    <!-- Current username info -->
    <div class="current-section">
        <SettingsSectionHeading title={$text('settings.account.username.current')} icon="user" />
        <p class="current-value">{currentUsername || '—'}</p>
    </div>

    <!-- Input -->
    <div class="input-section">
        <label class="input-label" for="username-input">
            {$text('settings.account.username.new')}
        </label>
        <SettingsInput
            id="username-input"
            bind:value={inputValue}
            type="text"
            autocomplete="username"
            spellcheck={false}
            maxlength={20}
            placeholder={$text('settings.account.username.placeholder')}
            hasError={!!validationError}
            disabled={isSaving}
            onBlur={() => { hasBlurred = true; }}
        />
        {#if validationError}
            <p class="field-error">{validationError}</p>
        {/if}
    </div>

    <!-- Status messages -->
    {#if errorMessage}
        <div class="message error">{errorMessage}</div>
    {/if}
    {#if successMessage}
        <div class="message success">{successMessage}</div>
    {/if}

    <!-- Save button -->
    <div class="action-section">
        <button
            class="save-btn"
            onclick={handleSave}
            disabled={isSaving || !hasChanges || !!validationError || isCheckingAvailability || usernameAlreadyTaken}
        >
            {isSaving
                ? $text('settings.account.username.saving')
                : $text('settings.account.username.save')}
        </button>
    </div>

    <!-- Info note -->
    <div class="info-box">
        <p>{$text('settings.account.username.info')}</p>
    </div>

</div>

<!-- ─── Styles ─────────────────────────────────────────────────────────────── -->

<style>
    .settings-username {
        padding: 0;
    }

    /* ── Current username display ── */

    .current-section {
        padding: 1rem 1rem 0.5rem;
    }


    .current-value {
        margin: 0;
        font-size: 1.1rem;
        font-weight: 500;
        color: var(--color-text-primary);
    }

    /* ── Input ── */

    .input-section {
        padding: 1rem 1rem 0;
    }

    .input-label {
        display: block;
        margin-bottom: 0.5rem;
        font-size: 0.9rem;
        color: var(--color-text-secondary);
    }

    .field-error {
        margin: 0.4rem 0 0;
        font-size: 0.85rem;
        color: var(--color-error);
    }

    /* ── Status messages ── */

    .message {
        margin: 0.75rem 1rem 0;
        padding: 0.75rem 1rem;
        border-radius: 8px;
        font-size: 0.9rem;
    }

    .message.error {
        background: var(--color-error-background, rgba(255, 0, 0, 0.08));
        color: var(--color-error);
        border: 1px solid var(--color-error);
    }

    .message.success {
        background: var(--color-success-background, rgba(0, 200, 0, 0.08));
        color: var(--color-success);
        border: 1px solid var(--color-success);
    }

    /* ── Save button ── */

    .action-section {
        padding: 1rem;
    }

    .save-btn {
        width: 100%;
        padding: 0.85rem 1rem;
        background: var(--color-primary);
        border: none;
        border-radius: 8px;
        color: #fff;
        font-size: 1rem;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.15s ease;
    }

    .save-btn:hover:not(:disabled) {
        opacity: 0.85;
    }

    .save-btn:disabled {
        opacity: 0.45;
        cursor: not-allowed;
    }

    /* ── Info box ── */

    .info-box {
        margin: 0.25rem 1rem 1.5rem;
        padding: 1rem;
        background: var(--color-background-secondary);
        border-radius: 8px;
        border: 1px solid var(--color-border);
    }

    .info-box p {
        margin: 0;
        font-size: 0.88rem;
        line-height: 1.5;
        color: var(--color-text-secondary);
    }
</style>
