<script lang="ts">
    /**
     * InputWarning Component
     * 
     * Displays a warning tooltip above an input element.
     * Uses position: absolute relative to the parent .input-wrapper,
     * which avoids issues with CSS transforms on ancestor elements
     * (like Svelte's in:scale transition on .login-box).
     * 
     * IMPORTANT: This component expects to be rendered inside an element
     * with position: relative (like .input-wrapper in fields.css).
     */
    import { fade } from 'svelte/transition';
    import { onMount } from 'svelte';
    
    // Props using Svelte 5 runes mode
    // Note: 'target' prop was removed - positioning is now done via CSS
    // relative to the parent .input-wrapper element
    let { 
        message, 
        autoHideDelay = 3000 
    }: { 
        message: string, 
        autoHideDelay?: number 
    } = $props();
    
    // State variables using Svelte 5 runes
    let warning = $state<HTMLElement>();
    let hideTimer = $state<ReturnType<typeof setTimeout>>();
    let visible = $state(true);
    
    onMount(() => {
        // Set auto-hide timer
        if (autoHideDelay > 0) {
            hideTimer = setTimeout(() => {
                visible = false;
            }, autoHideDelay);
        }
        
        return () => {
            if (hideTimer) clearTimeout(hideTimer);
        };
    });
</script>

{#if visible}
    <div
        bind:this={warning}
        class="warning"
        transition:fade
    >
        {@html message}
        <div class="arrow"></div>
    </div>
{/if}

<style>
    /**
     * Warning tooltip positioned absolutely above the input.
     * Uses position: absolute instead of position: fixed to avoid
     * issues with CSS transforms on ancestor elements creating
     * new containing blocks that break fixed positioning.
     * 
     * The parent element (.input-wrapper) has position: relative,
     * so this positions relative to that wrapper.
     */
    .warning {
        position: absolute;
        /* Position above the input: move up by 100% of own height plus 8px gap */
        bottom: calc(100% + 8px);
        /* Center horizontally */
        left: 50%;
        transform: translateX(-50%);
        background-color: #E00000;
        color: white;
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 14px;
        z-index: 10000;
        white-space: nowrap;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        text-align: center;
    }

    .arrow {
        position: absolute;
        left: 50%;
        bottom: -4px;
        transform: translateX(-50%);
        width: 0;
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 5px solid #E00000;
    }
</style>
