<!--
    SettingsCheckboxList — List of checkable items with icon, label, and description.

    Replaces `.export-options-list`, `.option-item`, `.option-label` patterns
    across settings pages with a single canonical component. Supports nested
    indented sub-items and optional icons via CSS mask.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    /** Shape of each checkbox option */
    type CheckboxOption = {
        id: string;
        label: string;
        description?: string;
        icon?: string;
        checked: boolean;
    };

    let {
        options = $bindable<CheckboxOption[]>([]),
        nested = false,
        onChange = undefined,
    }: {
        options: CheckboxOption[];
        nested?: boolean;
        onChange?: ((id: string, checked: boolean) => void) | undefined;
    } = $props();

    function handleToggle(option: CheckboxOption) {
        option.checked = !option.checked;
        onChange?.(option.id, option.checked);
    }

    function handleKeydown(event: KeyboardEvent, option: CheckboxOption) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleToggle(option);
        }
    }
</script>

<div class="settings-checkbox-list-wrapper">
    <ul class="settings-checkbox-list" class:nested role="list">
        {#each options as option (option.id)}
            <li
                class="checkbox-item"
                onclick={() => handleToggle(option)}
                onkeydown={(e) => handleKeydown(e, option)}
                role="option"
                aria-selected={option.checked}
                tabindex="0"
            >
                <input
                    type="checkbox"
                    class="checkbox-input"
                    checked={option.checked}
                    aria-label={option.label}
                    tabindex="-1"
                    onclick={(e) => e.stopPropagation()}
                    onchange={() => handleToggle(option)}
                />
                {#if option.icon}
                    <span class="checkbox-icon clickable-icon {option.icon}"></span>
                {/if}
                <div class="checkbox-content">
                    <span class="checkbox-label">{option.label}</span>
                    {#if option.description}
                        <span class="checkbox-description">{option.description}</span>
                    {/if}
                </div>
            </li>
        {/each}
    </ul>
</div>

<style>
    .settings-checkbox-list-wrapper {
        padding: 0 0.625rem;
    }

    .settings-checkbox-list {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    /* ── Nested variant ────────────────────────────────────────── */
    .settings-checkbox-list.nested {
        margin-left: 2rem;
    }

    .settings-checkbox-list.nested .checkbox-item {
        background: var(--color-grey-0);
        border: 0.0625rem solid var(--color-grey-25);
    }

    /* ── Item ──────────────────────────────────────────────────── */
    .checkbox-item {
        display: flex;
        align-items: flex-start;
        gap: 0.75rem;
        cursor: pointer;
        padding: 0.625rem 0.75rem;
        border-radius: 0.5rem;
        transition: background var(--duration-normal) var(--easing-default);
    }

    .checkbox-item:hover {
        background: var(--color-grey-10);
    }

    .checkbox-item:focus-visible {
        outline: 0.125rem solid var(--color-primary-start);
        outline-offset: 0.125rem;
    }

    /* ── Checkbox input ────────────────────────────────────────── */
    .checkbox-input {
        width: 1rem;
        height: 1rem;
        accent-color: var(--color-primary-start);
        flex-shrink: 0;
        margin-top: 0.125rem;
        cursor: pointer;
    }

    /* ── Icon ──────────────────────────────────────────────────── */
    .checkbox-icon {
        width: 1.125rem;
        height: 1.125rem;
        background-color: var(--color-font-secondary);
        flex-shrink: 0;
    }

    /* ── Content ───────────────────────────────────────────────── */
    .checkbox-content {
        display: flex;
        flex-direction: column;
    }

    .checkbox-label {
        font-size: var(--font-size-p, 0.875rem);
        font-weight: 500;
        background: var(--color-primary);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    .checkbox-description {
        font-size: var(--processing-details-font-size, 0.8125rem);
        color: var(--color-font-secondary);
        margin-top: 0.125rem;
    }
</style>
