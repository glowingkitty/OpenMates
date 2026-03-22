<script lang="ts">
    import { createEventDispatcher } from 'svelte';

    // Props for the toggle component using Svelte 5 $props()
    // checked is $bindable so callers using bind:checked still work,
    // but the input is driven by the prop directly (no internal bind:checked)
    // so the DOM always reflects what the parent passes in.
    interface Props {
        checked?: boolean;
        disabled?: boolean;
        name?: string;
        ariaLabel?: string;
        id?: string;
    }
    let { 
        checked = $bindable(false),
        disabled = false,
        name = '',
        ariaLabel = '',
        id = ''
    }: Props = $props();

    const dispatch = createEventDispatcher();

    // Handle toggle change with proper event typing.
    // We update the bindable prop and dispatch so callers using bind:checked
    // still receive the new value. The input's checked attribute is driven
    // directly by the prop so the DOM stays in sync.
    function handleChange(event: Event) {
        checked = (event.target as HTMLInputElement).checked;
        dispatch('change', { checked }); 
    }
</script>

<label class="toggle" class:disabled>
    <input
        type="checkbox"
        {id}
        {name}
        {disabled}
        checked={checked}
        onchange={handleChange}
        aria-label={ariaLabel}
    />
    <span class="slider"></span>
</label>

<style>
    .toggle {
        position: relative;
        display: inline-block;
        width: 52px;
        height: 32px;
        min-width: 52px; /* Prevent width from being compressed */
        flex-shrink: 0; /* Prevent flexbox from shrinking the toggle */
        cursor: pointer;
    }

    .toggle.disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    input {
        opacity: 0;
        width: 0;
        height: 0;
    }

    .slider {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: var(--color-grey-30);
        border-radius: 34px;
        transition: all 0.3s;
        box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.2);
    }

    .slider:before {
        position: absolute;
        content: "";
        height: 24px;
        width: 24px;
        left: 4px;
        bottom: 4px;
        background-color: white;
        border-radius: 50%;
        transition: 0.3s;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
    }

    input:checked + .slider {
        background: var(--color-primary);
    }

    input:checked + .slider:before {
        transform: translateX(20px);
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
    }
</style>