<script lang="ts">
    // Props for the toggle component
    export let checked = false;  // Initial state
    export let disabled = false; // Optional disabled state
    export let name = '';       // For form identification
    export let ariaLabel = '';  // For accessibility

    // Handle toggle change with proper event typing
    function handleChange(event: Event) {
        checked = (event.target as HTMLInputElement).checked;
    }
</script>

<label class="toggle" class:disabled>
    <input
        type="checkbox"
        {name}
        {disabled}
        bind:checked
        on:change={handleChange}
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