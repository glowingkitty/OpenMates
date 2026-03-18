<!--
    SettingsQuote — Quoted text card for examples and prompts.

    Matches Figma "Quoted text" element:
    White background, 19px border-radius, box-shadow, quote icons at
    top-right and bottom-left. Optionally clickable (e.g. copy to input).
    Can be grouped in a horizontal scrollable container.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    let {
        text = '',
        onClick = undefined,
        ariaLabel = '',
    }: {
        text?: string;
        onClick?: (() => void) | undefined;
        ariaLabel?: string;
    } = $props();

    let isClickable = $derived(onClick !== undefined);

    function handleClick() {
        onClick?.();
    }

    function handleKeydown(event: KeyboardEvent) {
        if (isClickable && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            handleClick();
        }
    }
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div
    class="settings-quote"
    class:clickable={isClickable}
    onclick={isClickable ? handleClick : undefined}
    onkeydown={isClickable ? handleKeydown : undefined}
    role={isClickable ? 'button' : 'blockquote'}
    tabindex={isClickable ? 0 : undefined}
    aria-label={ariaLabel || text}
>
    <!-- Top-right quote icon -->
    <svg class="quote-icon quote-icon-top" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M14.017 21v-7.391c0-5.704 3.731-9.57 8.983-10.609l.995 2.151c-2.432.917-3.995 3.638-3.995 5.849h4v10h-9.983zm-14.017 0v-7.391c0-5.704 3.748-9.57 9-10.609l.996 2.151c-2.433.917-3.996 3.638-3.996 5.849h3.983v10h-9.983z"/>
    </svg>

    <!-- Quote text -->
    <p class="quote-text">{text}</p>

    <!-- Bottom-left quote icon (rotated 180deg) -->
    <svg class="quote-icon quote-icon-bottom" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M14.017 21v-7.391c0-5.704 3.731-9.57 8.983-10.609l.995 2.151c-2.432.917-3.995 3.638-3.995 5.849h4v10h-9.983zm-14.017 0v-7.391c0-5.704 3.748-9.57 9-10.609l.996 2.151c-2.433.917-3.996 3.638-3.996 5.849h3.983v10h-9.983z"/>
    </svg>
</div>

<style>
    .settings-quote {
        position: relative;
        /* Top padding makes room for the quote icon at top-right */
        padding: 2rem 1.5rem;
        background: var(--color-grey-0);
        border-radius: 1.1875rem;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        min-width: 12rem;
        min-height: 7rem;
        transition: box-shadow 0.2s ease, transform 0.2s ease;
        /* Center text vertically in the available space */
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .settings-quote.clickable {
        cursor: pointer;
    }

    .settings-quote.clickable:hover {
        box-shadow: 0 0.375rem 0.5rem rgba(0, 0, 0, 0.15);
        transform: translateY(-0.0625rem);
    }

    .settings-quote.clickable:focus-visible {
        outline: 0.125rem solid var(--color-primary-start);
        outline-offset: 0.125rem;
    }

    .quote-icon {
        position: absolute;
        color: var(--color-grey-40);
    }

    .quote-icon-top {
        top: 0.5625rem;
        right: 0.75rem;
    }

    .quote-icon-bottom {
        bottom: 0.75rem;
        left: 0.75rem;
        transform: rotate(180deg);
    }

    .quote-text {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-weight: 700;
        font-size: 0.875rem;
        line-height: 1.25;
        color: var(--color-grey-70);
        margin: 0;
        text-align: center;
    }
</style>
