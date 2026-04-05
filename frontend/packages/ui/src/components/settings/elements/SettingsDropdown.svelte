<!--
    SettingsDropdown — Shared dropdown select for settings pages.

    Matches Figma "Input field - Dropdown" element:
    White background, 24px border-radius, box-shadow, dropdown chevron icon
    on the right. Always follows after a Settings subheading.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    /** Individual dropdown option */
    interface DropdownOption {
        value: string;
        label: string;
    }

    let {
        value = $bindable(''),
        options = [],
        placeholder = '',
        disabled = false,
        name = '',
        ariaLabel = '',
        onChange = undefined,
    }: {
        value?: string;
        options?: DropdownOption[];
        placeholder?: string;
        disabled?: boolean;
        name?: string;
        ariaLabel?: string;
        onChange?: ((value: string) => void) | undefined;
    } = $props();

    function handleChange(event: Event) {
        const target = event.target as HTMLSelectElement;
        value = target.value;
        onChange?.(value);
    }
</script>

<div class="settings-dropdown-wrapper">
    <div class="settings-dropdown-container">
        <select
            class="settings-dropdown"
            data-testid="settings-dropdown"
            {name}
            {disabled}
            aria-label={ariaLabel || placeholder}
            bind:value
            onchange={handleChange}
        >
            {#if placeholder}
                <option value="" disabled selected>{placeholder}</option>
            {/if}
            {#each options as option}
                <option value={option.value}>{option.label}</option>
            {/each}
        </select>
        <div class="dropdown-chevron" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
        </div>
    </div>
</div>

<style>
    .settings-dropdown-wrapper {
        padding: 0 0.625rem;
    }

    .settings-dropdown-container {
        position: relative;
        width: 100%;
    }

    .settings-dropdown {
        width: 100%;
        padding: 1.0625rem 3rem 1.0625rem 1.4375rem;
        background: var(--color-grey-0);
        border: none;
        border-radius: 1.5rem;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-weight: 500;
        font-size: var(--input-font-size, 1rem);
        line-height: 1.25;
        color: var(--color-grey-100);
        cursor: pointer;
        appearance: none;
        -webkit-appearance: none;
        transition: box-shadow var(--duration-normal) var(--easing-default);
    }

    /* Placeholder-like styling for unselected state */
    .settings-dropdown:invalid,
    .settings-dropdown option[value=""][disabled] {
        color: var(--color-grey-50);
    }

    .settings-dropdown:focus {
        box-shadow: 0 0.25rem 0.5rem rgba(0, 0, 0, 0.15),
                    0 0 0 0.125rem var(--color-primary-start);
    }

    .settings-dropdown:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .dropdown-chevron {
        position: absolute;
        right: 1rem;
        top: 50%;
        transform: translateY(-50%);
        pointer-events: none;
        color: var(--color-grey-50);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .settings-dropdown option {
        background: var(--color-grey-0);
        color: var(--color-grey-100);
    }
</style>
