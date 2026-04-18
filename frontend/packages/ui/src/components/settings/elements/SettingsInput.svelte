<!--
    SettingsInput — Shared short text input for settings pages.

    Matches Figma "Input field - Short text" element:
    White background, 24px border-radius, box-shadow, placeholder grey.
    Always follows after a Settings subheading (SettingsItem type="heading").

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    /** Input type — standard HTML input types */
    type InputType = 'text' | 'email' | 'password' | 'number' | 'search' | 'url' | 'tel' | 'date' | 'time';

    /** inputmode — virtual keyboard hint for mobile */
    type InputMode = 'none' | 'text' | 'decimal' | 'numeric' | 'tel' | 'search' | 'email' | 'url';

    let {
        value = $bindable(''),
        placeholder = '',
        type = 'text' as InputType,
        disabled = false,
        name = '',
        id = '',
        ariaLabel = '',
        autocomplete = 'off',
        spellcheck = undefined as boolean | undefined,
        maxlength = undefined,
        pattern = undefined as string | undefined,
        inputmode = undefined as InputMode | undefined,
        min = undefined as string | undefined,
        hasError = false,
        dataTestid = '',
        onInput = undefined,
        onKeydown = undefined,
        onBlur = undefined,
        inputRef = $bindable(undefined),
    }: {
        value?: string;
        placeholder?: string;
        type?: InputType;
        disabled?: boolean;
        name?: string;
        id?: string;
        ariaLabel?: string;
        autocomplete?: string;
        spellcheck?: boolean | undefined;
        maxlength?: number | undefined;
        min?: string | undefined;
        pattern?: string | undefined;
        inputmode?: InputMode | undefined;
        hasError?: boolean;
        dataTestid?: string;
        onInput?: ((value: string) => void) | undefined;
        onKeydown?: ((event: KeyboardEvent) => void) | undefined;
        onBlur?: (() => void) | undefined;
        /**
         * Optional ref binding — exposes the underlying <input> DOM element.
         * Use when you need programmatic focus: bind:inputRef={myInputEl}
         * then call myInputEl?.focus().
         */
        inputRef?: HTMLInputElement | undefined;
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
        class:error={hasError}
        {type}
        {name}
        {id}
        {placeholder}
        {disabled}
        {autocomplete}
        spellcheck={spellcheck}
        maxlength={maxlength}
        min={min}
        pattern={pattern}
        inputmode={inputmode}
        aria-label={ariaLabel || placeholder}
        aria-invalid={hasError || undefined}
        data-testid={dataTestid || 'settings-input'}
        bind:this={inputRef}
        bind:value
        oninput={handleInput}
        onkeydown={onKeydown}
        onblur={onBlur}
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
        transition: box-shadow var(--duration-normal) var(--easing-default);
        box-sizing: border-box;
    }

    .settings-input::placeholder {
        color: var(--color-grey-50);
    }

    .settings-input:focus {
        box-shadow: 0 0.25rem 0.5rem rgba(0, 0, 0, 0.15),
                    0 0 0 0.125rem var(--color-primary-start);
    }

    .settings-input.error {
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1),
                    0 0 0 0.125rem var(--color-error, #e74c3c);
    }

    .settings-input:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
</style>
