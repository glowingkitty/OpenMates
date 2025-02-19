<script lang="ts">
    import { fade } from 'svelte/transition';
    import { onMount } from 'svelte';
    
    export let message: string;
    export let target: HTMLElement;
    
    let warning: HTMLElement;
    let position = { top: 0, left: 0 };
    
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
        
        return () => {
            window.removeEventListener('scroll', updatePosition);
            window.removeEventListener('resize', updatePosition);
        };
    });
    
    $: if (target) updatePosition();
</script>

<div 
    bind:this={warning}
    class="warning"
    style="left: {position.left}px; top: {position.top}px"
    transition:fade
>
    {message}
    <div class="arrow"></div>
</div>

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
