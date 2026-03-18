<!--
    SettingsInput — Shared short text input for settings pages.

    Matches Figma "Input field - Short text" element:
    White background, 24px border-radius, box-shadow, placeholder #8A8A8A.
    Always follows after a Settings subheading (SettingsItem type="heading").

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    /** Input type — standard HTML input types */
    type InputType = 'text' | 'email' | 'password' | 'number' | 'search' | 'url' | 'tel';

    let {
        value = $bindable(''),
        placeholder = '',
        type = 'text' as InputType,
        disabled = false,
        name = '',
        ariaLabel = '',
        autocomplete = 'off',
        maxlength = undefined,
        onInput = undefined,
        onKeydown = undefined,
    }: {
        value?: string;
        placeholder?: string;
        type?: InputType;
        disabled?: boolean;
        name?: string;
        ariaLabel?: string;
        autocomplete?: string;
        maxlength?: number | undefined;
        onInput?: ((value: string) => void) | undefined;
        onKeydown?: ((event: KeyboardEvent) => void) | undefined;
    } = $props();

    function handleInput(event: Event) {
        const target = event.target as HTMLInputElement;
        value = target.value;
        onInput?.(value);
    }
</script>

<div class="settings-input-wrapper">
    <input
        class="settings-input"
        {type}
        {name}
        {placeholder}
        {disabled}
        {autocomplete}
        maxlength={maxlength}
        aria-label={ariaLabel || placeholder}
        bind:value
        oninput={handleInput}
        onkeydown={onKeydown}
    />
</div>

<style>
    .settings-input-wrapper {
        padding: 0 0.625rem;
    }

    .settings-input {
        width: 100%;
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
        outline: none;
        transition: box-shadow 0.2s ease;
        box-sizing: border-box;
    }

    .settings-input::placeholder {
        color: var(--color-grey-50);
    }

    .settings-input:focus {
        box-shadow: 0 0.25rem 0.5rem rgba(0, 0, 0, 0.15),
                    0 0 0 0.125rem var(--color-primary-start);
    }

    .settings-input:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
</style>
