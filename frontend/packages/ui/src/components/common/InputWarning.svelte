<script lang="ts">
    import { fade } from 'svelte/transition';
    import { onMount } from 'svelte';
    
    // Props using Svelte 5 runes mode
    let { 
        message, 
        target, 
        autoHideDelay = 3000 
    }: { 
        message: string, 
        target: HTMLElement, 
        autoHideDelay?: number 
    } = $props();
    
    // State variables using Svelte 5 runes
    let warning = $state<HTMLElement>();
    let position = $state({ top: 0, left: 0 });
    let hideTimer = $state<ReturnType<typeof setTimeout>>();
    let visible = $state(true);
    
    function updatePosition() {
        if (!target) return;
        const rect = target.getBoundingClientRect();
        position = {
            top: rect.top - 8,
            left: rect.left + (rect.width / 2)
        };
    }
    
    onMount(() => {
        updatePosition();
        // Update position on scroll and resize
        window.addEventListener('scroll', updatePosition);
        window.addEventListener('resize', updatePosition);
        
        // Set auto-hide timer
        if (autoHideDelay > 0) {
            hideTimer = setTimeout(() => {
                visible = false;
            }, autoHideDelay);
        }
        
        return () => {
            window.removeEventListener('scroll', updatePosition);
            window.removeEventListener('resize', updatePosition);
            if (hideTimer) clearTimeout(hideTimer);
        };
    });
    
    // Watch for target changes using Svelte 5 runes
    $effect(() => {
        if (target) updatePosition();
    });
</script>

{#if visible}
    <div
        bind:this={warning}
        class="warning"
        style="left: {position.left}px; top: {position.top}px"
        transition:fade
    >
        {@html message}
        <div class="arrow"></div>
    </div>
{/if}

<style>
    .warning {
        position: fixed;
        transform: translateX(-50%) translateY(-100%);
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
