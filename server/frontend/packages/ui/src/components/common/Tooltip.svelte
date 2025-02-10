<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    
    // Props
    export let element: HTMLElement | null = null;
    
    // State
    let tooltip: HTMLElement;
    let showTooltip = false;
    let timeoutId: ReturnType<typeof setTimeout>;
    let position = { x: 0, y: 0 };
    
    // Constants
    const TOOLTIP_DELAY = 1000; // 1 second delay before showing tooltip
    const TOOLTIP_OFFSET = 8; // Pixels to offset tooltip from element
    
    function showTooltipWithDelay(event: MouseEvent) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
            if (!element) return;
            
            const rect = element.getBoundingClientRect();
            const scrollY = window.scrollY;
            const scrollX = window.scrollX;
            
            // Calculate the initial position (above the element)
            let newPosition = {
                x: rect.left + (rect.width / 2) + scrollX,
                y: rect.top - TOOLTIP_OFFSET + scrollY
            };
            
            showTooltip = true;
            
            // We need to wait for the tooltip to be rendered to get its height.
            // Use requestAnimationFrame to ensure the tooltip is rendered before measuring.
            requestAnimationFrame(() => {
                if (tooltip) {
                    const tooltipRect = tooltip.getBoundingClientRect();
                    
                    // Check if there's enough space above
                    if (newPosition.y - tooltipRect.height < 0) {
                        // Not enough space above, position below the element
                        newPosition.y = rect.bottom + TOOLTIP_OFFSET + scrollY;
                        //Adjust the arrow position
                        tooltip.querySelector('.tooltip-arrow')?.setAttribute('style', 'top: -4px; border-top: none; border-bottom: 5px solid var(--color-grey-0);');
                        
                    } else {
                        // Reset the arrow position in case it was previously adjusted
                        tooltip.querySelector('.tooltip-arrow')?.setAttribute('style', '');
                    }
                }
                // Apply the calculated (and potentially adjusted) position
                position = newPosition;
            });
            
        }, TOOLTIP_DELAY);
    }
    
    function hideTooltip() {
        clearTimeout(timeoutId);
        showTooltip = false;
    }
    
    onMount(() => {
        if (!element) return;
        
        element.addEventListener('mouseenter', showTooltipWithDelay);
        element.addEventListener('mouseleave', hideTooltip);
        element.addEventListener('focus', showTooltipWithDelay);
        element.addEventListener('blur', hideTooltip);
        console.log("Tooltip mounted"); // logging using console.log
    });
    
    onDestroy(() => {
        if (!element) return;
        
        element.removeEventListener('mouseenter', showTooltipWithDelay);
        element.removeEventListener('mouseleave', hideTooltip);
        element.removeEventListener('focus', showTooltipWithDelay);
        element.removeEventListener('blur', hideTooltip);
        clearTimeout(timeoutId);
        console.log("Tooltip destroyed"); // logging using console.log
    });
</script>

{#if showTooltip && element?.getAttribute('aria-label')}
    <div
        bind:this={tooltip}
        class="tooltip"
        style="left: {position.x}px; top: {position.y}px"
        role="tooltip"
    >
        {element.getAttribute('aria-label')}
        <div class="tooltip-arrow"></div>
    </div>
{/if}

<style>
    .tooltip {
        position: fixed;
        transform: translateX(-50%) translateY(-100%);
        background-color: var(--color-grey-0);
        color: var(--color-font-inverse);
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 14px;
        z-index: 10000;
        pointer-events: none;
        white-space: nowrap;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        max-width: 300px;
        text-align: center;
    }

    .tooltip-arrow {
        position: absolute;
        bottom: -4px;
        left: 50%;
        transform: translateX(-50%);
        width: 0;
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 5px solid var(--color-grey-0);
    }
</style> 