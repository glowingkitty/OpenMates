<!--
    SettingsDropdown — Shared dropdown select for settings pages.

    Matches Figma "Input field - Dropdown" element:
    White background, 24px border-radius, box-shadow, dropdown chevron icon
    on the right. Always follows after a Settings subheading.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import { onMount } from 'svelte';

    /** Individual dropdown option */
    interface DropdownOption {
        value: string;
        label: string;
        /** CSS custom properties for a masked icon, such as --workflow-icon. */
        iconStyle?: string;
        /** Color or gradient used behind the icon or symbol. */
        iconBackground?: string;
        /** A short symbol to show instead of an icon mask. */
        iconText?: string;
    }

    let {
        value = $bindable(''),
        options = [],
        placeholder = '',
        disabled = false,
        name = '',
        ariaLabel = '',
        dataTestid = '',
        rich = false,
        onChange = undefined,
    }: {
        value?: string;
        options?: DropdownOption[];
        placeholder?: string;
        disabled?: boolean;
        name?: string;
        ariaLabel?: string;
        dataTestid?: string;
        rich?: boolean;
        onChange?: ((value: string) => void) | undefined;
    } = $props();

    let trigger = $state<HTMLButtonElement>();
    let open = $state(false);
    let activeIndex = $state(0);
    let popupTop = $state(0);
    let popupLeft = $state(0);
    let popupWidth = $state(0);
    let popupMaxHeight = $state(240);
    let popupAbove = $state(false);
    let listboxId = $state('');
    const selectedOption = $derived(options.find(option => option.value === value));

    function iconMask(option: DropdownOption): string {
        return option.iconStyle?.match(/--workflow-icon:\s*([^;]+)/)?.[1] ?? 'var(--icon-url-app)';
    }

    function positionPopup() {
        if (!trigger) return;
        const rect = trigger.getBoundingClientRect();
        const roomBelow = window.innerHeight - rect.bottom - 8;
        const roomAbove = rect.top - 8;
        popupAbove = roomBelow < 176 && roomAbove > roomBelow;
        popupMaxHeight = Math.max(64, Math.min(280, (popupAbove ? roomAbove : roomBelow) - 4));
        popupTop = popupAbove ? Math.max(8, rect.top - popupMaxHeight - 4) : rect.bottom + 4;
        popupLeft = Math.max(8, Math.min(rect.left, window.innerWidth - Math.min(rect.width, window.innerWidth - 16) - 8));
        popupWidth = Math.min(rect.width, window.innerWidth - 16);
    }

    function openPopup(index?: number) {
        if (disabled || !options.length) return;
        activeIndex = index ?? Math.max(0, options.findIndex(option => option.value === value));
        positionPopup();
        open = true;
    }

    function chooseOption(index: number) {
        const option = options[index];
        if (!option) return;
        value = option.value;
        onChange?.(option.value);
        open = false;
        trigger?.focus();
    }

    function handleRichKeydown(event: KeyboardEvent) {
        if (disabled) return;
        if (event.key === 'Escape') {
            if (open) { event.preventDefault(); open = false; }
            return;
        }
        if (event.key === 'Tab') { open = false; return; }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Home' || event.key === 'End') {
            event.preventDefault();
            if (!open) {
                openPopup(event.key === 'End' ? options.length - 1 : event.key === 'Home' ? 0 : undefined);
                return;
            }
            activeIndex = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : Math.max(0, Math.min(options.length - 1, activeIndex + (event.key === 'ArrowDown' ? 1 : -1)));
            document.getElementById(`${listboxId}-option-${activeIndex}`)?.scrollIntoView({ block: 'nearest' });
            return;
        }
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            if (open) chooseOption(activeIndex);
            else openPopup();
        }
    }

    onMount(() => {
        listboxId = `settings-dropdown-${crypto.randomUUID()}`;
        const closeOutside = (event: PointerEvent) => {
            if (!open || !(event.target instanceof Node)) return;
            if (trigger?.contains(event.target) || document.getElementById(listboxId)?.contains(event.target)) return;
            open = false;
        };
        const updatePosition = () => { if (open) positionPopup(); };
        document.addEventListener('pointerdown', closeOutside);
        window.addEventListener('resize', updatePosition);
        window.addEventListener('scroll', updatePosition, true);
        return () => {
            document.removeEventListener('pointerdown', closeOutside);
            window.removeEventListener('resize', updatePosition);
            window.removeEventListener('scroll', updatePosition, true);
        };
    });

    function handleChange(event: Event) {
        const target = event.target as HTMLSelectElement;
        value = target.value;
        onChange?.(value);
    }
</script>

<div class="settings-dropdown-wrapper">
    <div class="settings-dropdown-container">
        {#if rich}
        {#if name}<input type="hidden" {name} {value} data-testid="settings-dropdown-value" />{/if}
        <button
            bind:this={trigger}
            type="button"
            class="settings-dropdown rich-trigger"
            class:unselected={!selectedOption}
            data-testid={dataTestid || 'settings-dropdown'}
            {disabled}
            role="combobox"
            aria-label={ariaLabel || placeholder}
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-controls={open ? listboxId : undefined}
            aria-activedescendant={open ? `${listboxId}-option-${activeIndex}` : undefined}
            onclick={() => open ? open = false : openPopup()}
            onkeydown={handleRichKeydown}
        >
            {#if selectedOption?.iconStyle || selectedOption?.iconText}
                <span class="option-icon" style:background={selectedOption.iconBackground || 'var(--color-primary)'} aria-hidden="true">
                    {#if selectedOption.iconText}<span class="option-symbol">{selectedOption.iconText}</span>{:else}<span class="option-mask" style:--workflow-icon={iconMask(selectedOption)}></span>{/if}
                </span>
            {/if}
            <span class="rich-label">{selectedOption?.label || placeholder}</span>
        </button>
        {#if open}
            <div
                id={listboxId}
                class="rich-listbox"
                role="listbox"
                aria-label={ariaLabel || placeholder}
                style:top={`${popupTop}px`}
                style:left={`${popupLeft}px`}
                style:width={`${popupWidth}px`}
                style:max-height={`${popupMaxHeight}px`}
            >
                {#each options as option, index (option.value)}
                    <div
                        id={`${listboxId}-option-${index}`}
                        role="option"
                        tabindex="-1"
                        aria-selected={option.value === value}
                        class="rich-option"
                        class:active={index === activeIndex}
                        onclick={() => chooseOption(index)}
                        onkeydown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); chooseOption(index); } }}
                        onpointerenter={() => activeIndex = index}
                    >
                        {#if option.iconStyle || option.iconText}
                            <span class="option-icon" style:background={option.iconBackground || 'var(--color-primary)'} aria-hidden="true">
                                {#if option.iconText}<span class="option-symbol">{option.iconText}</span>{:else}<span class="option-mask" style:--workflow-icon={iconMask(option)}></span>{/if}
                            </span>
                        {/if}
                        <span>{option.label}</span>
                    </div>
                {/each}
            </div>
        {/if}
        {:else}
        <select
            class="settings-dropdown"
            data-testid={dataTestid || 'settings-dropdown'}
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
        {/if}
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
        box-shadow: var(--shadow-sm);
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
        box-shadow: var(--shadow-sm),
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

    .rich-trigger { display:flex; align-items:center; gap:.5rem; text-align:left; min-height:3.5rem; }
    .rich-trigger.unselected { color:var(--color-grey-50); }
    .rich-label { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .option-icon { display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; width:1.75rem; height:1.75rem; border-radius:.35rem; color:var(--color-font-button); }
    .option-mask { display:block; width:1rem; height:1rem; background:currentColor; -webkit-mask:var(--workflow-icon) center/contain no-repeat; mask:var(--workflow-icon) center/contain no-repeat; }
    .option-symbol { font-weight:700; line-height:1; }
    .rich-listbox { position:fixed; z-index:1000; box-sizing:border-box; overflow-y:auto; overscroll-behavior:contain; padding:.35rem; border-radius:1.25rem; background:var(--color-grey-0); box-shadow:var(--shadow-md); color:var(--color-grey-100); }
    .rich-option { display:flex; align-items:center; gap:.5rem; min-height:2.75rem; padding:.35rem .65rem; border-radius:.9rem; cursor:pointer; font-family:'Lexend Deca Variable',sans-serif; font-size:var(--input-font-size,1rem); font-weight:500; line-height:1.25; }
    .rich-option:hover,.rich-option.active { background:var(--color-grey-10); }
    .rich-option[aria-selected='true'] { color:var(--color-primary-start); }
    @media (pointer:coarse) { .rich-option { min-height:3rem; } }
</style>
