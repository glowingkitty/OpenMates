<!--
    SettingsTextarea — Shared multi-line text input for settings pages.

    Matches Figma "Input field - Multi line text" element:
    White background, 24px border-radius, box-shadow, placeholder #8A8A8A,
    taller default height (180px). Always follows after a Settings subheading.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    let {
        value = $bindable(''),
        placeholder = '',
        disabled = false,
        name = '',
        id = '',
        ariaLabel = '',
        rows = 6,
        maxlength = undefined,
        dataTestid = '',
        onInput = undefined,
    }: {
        value?: string;
        placeholder?: string;
        disabled?: boolean;
        name?: string;
        id?: string;
        ariaLabel?: string;
        rows?: number;
        maxlength?: number | undefined;
        dataTestid?: string;
        onInput?: ((value: string) => void) | undefined;
    } = $props();

    function handleInput(event: Event) {
        const target = event.target as HTMLTextAreaElement;
        value = target.value;
        onInput?.(value);
    }
</script>

<div class="settings-textarea-wrapper">
    <textarea
        class="settings-textarea"
        {name}
        id={id || undefined}
        {placeholder}
        {disabled}
        {rows}
        maxlength={maxlength}
        aria-label={ariaLabel || placeholder}
        data-testid={dataTestid || undefined}
        bind:value
        oninput={handleInput}
    ></textarea>
</div>

<style>
    .settings-textarea-wrapper {
        padding: 0 0.625rem;
    }

    .settings-textarea {
        width: 100%;
        min-height: 11.25rem;
        padding: 1.0625rem 1.4375rem;
        background: var(--color-grey-0);
        border: none;
        border-radius: 1.5rem;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-weight: 500;
        font-size: var(--input-font-size, 1rem);
        line-height: 1.25;
        color: var(--color-grey-100);
        transition: box-shadow 0.2s ease;
        resize: vertical;
        box-sizing: border-box;
    }

    .settings-textarea::placeholder {
        color: var(--color-grey-50);
    }

    .settings-textarea:focus {
        box-shadow: 0 0.25rem 0.5rem rgba(0, 0, 0, 0.15),
                    0 0 0 0.125rem var(--color-primary-start);
    }

    .settings-textarea:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
</style>
