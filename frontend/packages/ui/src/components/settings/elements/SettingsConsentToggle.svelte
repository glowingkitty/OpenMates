<!--
    SettingsConsentToggle — Consent acknowledgment with toggle on the LEFT.

    Matches Figma "Consent toggle" element:
    Toggle on LEFT side, consent text on RIGHT with important parts
    highlighted using the OpenMates primary gradient. User must toggle
    to confirm consent before proceeding with an action.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import Toggle from '../../Toggle.svelte';

    let {
        checked = $bindable(false),
        consentText = '',
        highlightedParts = [],
        disabled = false,
        ariaLabel = '',
        onChange = undefined,
    }: {
        checked?: boolean;
        consentText?: string;
        highlightedParts?: string[];
        disabled?: boolean;
        ariaLabel?: string;
        onChange?: ((checked: boolean) => void) | undefined;
    } = $props();

    /**
     * Parse consent text and split into segments for rendering.
     * Segments matching highlightedParts get the gradient treatment.
     */
    let segments = $derived.by(() => {
        if (!highlightedParts.length || !consentText) {
            return [{ text: consentText, highlighted: false }];
        }

        const result: Array<{ text: string; highlighted: boolean }> = [];
        let remaining = consentText;

        while (remaining.length > 0) {
            let earliestIndex = remaining.length;
            let matchedPart = '';

            // Find the earliest occurrence of any highlighted part
            for (const part of highlightedParts) {
                const idx = remaining.indexOf(part);
                if (idx !== -1 && idx < earliestIndex) {
                    earliestIndex = idx;
                    matchedPart = part;
                }
            }

            if (matchedPart && earliestIndex < remaining.length) {
                // Add non-highlighted text before the match
                if (earliestIndex > 0) {
                    result.push({ text: remaining.slice(0, earliestIndex), highlighted: false });
                }
                // Add highlighted match
                result.push({ text: matchedPart, highlighted: true });
                remaining = remaining.slice(earliestIndex + matchedPart.length);
            } else {
                // No more matches — add remaining text
                result.push({ text: remaining, highlighted: false });
                remaining = '';
            }
        }

        return result;
    });

    function handleToggleClick() {
        if (!disabled) {
            checked = !checked;
            onChange?.(checked);
        }
    }

    function handleKeydown(event: KeyboardEvent) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleToggleClick();
        }
    }
</script>

{#snippet toggleContent()}
    <div class="consent-toggle-left">
        <Toggle
            {checked}
            {disabled}
            ariaLabel={ariaLabel || 'Consent toggle'}
        />
    </div>
    <div class="consent-text">
        {#each segments as segment}
            {#if segment.highlighted}
                <span class="highlighted">{segment.text}</span>
            {:else}
                <span>{segment.text}</span>
            {/if}
        {/each}
    </div>
{/snippet}

{#if disabled}
<div
    class="settings-consent-toggle disabled"
    onclick={handleToggleClick}
    onkeydown={handleKeydown}
    role="checkbox"
    aria-checked={checked}
    aria-label={ariaLabel || consentText}
    tabindex="-1"
>
    {@render toggleContent()}
</div>
{:else}
<div
    class="settings-consent-toggle"
    onclick={handleToggleClick}
    onkeydown={handleKeydown}
    role="checkbox"
    aria-checked={checked}
    aria-label={ariaLabel || consentText}
    tabindex="0"
>
    {@render toggleContent()}
</div>
{/if}

<style>
    .settings-consent-toggle {
        display: flex;
        align-items: flex-start;
        gap: 1.25rem;
        padding: 0.625rem;
        border-radius: 0.5rem;
        cursor: pointer;
        transition: background-color var(--duration-normal) var(--easing-default);
    }

    .settings-consent-toggle:hover {
        background-color: var(--color-grey-10);
    }

    .settings-consent-toggle:focus-visible {
        outline: 0.125rem solid var(--color-primary-start);
        outline-offset: 0.125rem;
    }

    .settings-consent-toggle.disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .consent-toggle-left {
        flex-shrink: 0;
        padding-top: 0.0625rem;
    }

    .consent-text {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-weight: 500;
        font-size: var(--font-size-p, 1rem);
        line-height: 1.25;
        color: var(--color-grey-100);
    }

    .consent-text .highlighted {
        background: var(--color-primary);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 700;
    }
</style>
