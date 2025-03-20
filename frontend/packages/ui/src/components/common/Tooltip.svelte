<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    
    // Props
    export let element: HTMLElement | null = null;
    
    // State
    let tooltip: HTMLElement;
    let showTooltip = false;
    let timeoutId: ReturnType<typeof setTimeout>;
    let position = { x: 0, y: 0 };
    let isAbove = true; // tracks if tooltip is above or below element
    let isTouchDevice = false;
    
    // Constants
    const TOOLTIP_DELAY = 1000; // 1 second delay before showing tooltip
    const TOOLTIP_OFFSET = 8; // Pixels to offset tooltip from element
    
    // Check if device is touch-enabled
    function checkTouchDevice() {
        isTouchDevice = ('ontouchstart' in window) || 
            (navigator.maxTouchPoints > 0) || 
            // @ts-ignore
            (navigator.msMaxTouchPoints > 0);
        console.debug('Touch device detected:', isTouchDevice); // Debug log
    }
    
    function showTooltipWithDelay(event: MouseEvent) {
        // Don't show tooltip on touch devices
        if (isTouchDevice) {
            console.debug('Preventing tooltip on touch device'); // Debug log
            return;
        }
        
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
            if (!element) return;
            
            const rect = element.getBoundingClientRect();
            const scrollY = window.scrollY;
            const scrollX = window.scrollX;
            
            let newPosition = {
                x: rect.left + (rect.width / 2) + scrollX,
                y: rect.top - TOOLTIP_OFFSET + scrollY
            };
            
            showTooltip = true;
            
            requestAnimationFrame(() => {
                if (tooltip) {
                    const tooltipRect = tooltip.getBoundingClientRect();
                    const arrow = tooltip.querySelector('.tooltip-arrow');
                    
                    if (newPosition.y - tooltipRect.height < 0) {
                        // Position below the element
                        newPosition.y = rect.bottom + TOOLTIP_OFFSET + scrollY;
                        isAbove = false;
                        // Arrow points upward when tooltip is below
                        arrow?.setAttribute('style', 'top: -4px; bottom: auto; border-top: none; border-bottom: 5px solid var(--color-grey-0);');
                    } else {
                        // Position above the element
                        isAbove = true;
                        // Arrow points downward when tooltip is above
                        arrow?.setAttribute('style', 'bottom: -4px; top: auto; border-bottom: none; border-top: 5px solid var(--color-grey-0);');
                    }
                }
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
        
        // Check for touch device on mount
        checkTouchDevice();
        
        element.addEventListener('mouseenter', showTooltipWithDelay);
        element.addEventListener('mouseleave', hideTooltip);
        element.addEventListener('focus', showTooltipWithDelay);
        element.addEventListener('blur', hideTooltip);
    });
    
    onDestroy(() => {
        if (!element) return;
        
        element.removeEventListener('mouseenter', showTooltipWithDelay);
        element.removeEventListener('mouseleave', hideTooltip);
        element.removeEventListener('focus', showTooltipWithDelay);
        element.removeEventListener('blur', hideTooltip);
        clearTimeout(timeoutId);
    });
</script>

{#if showTooltip && element?.getAttribute('aria-label')}
    <div
        bind:this={tooltip}
        class="tooltip"
        class:above={isAbove}
        class:below={!isAbove}
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
        background-color: var(--color-grey-0);
        color: var(--color-grey-100);
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 14px;
        z-index: 10000;
        pointer-events: none;
        white-space: nowrap;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        max-width: 300px;
        text-align: center;
        /* Remove the default transform and handle it in the position classes */
        transform: translateX(-50%);
    }

    /* Position-specific transforms */
    .tooltip.above {
        transform: translateX(-50%) translateY(-100%);
    }

    .tooltip.below {
        transform: translateX(-50%);
    }

    .tooltip-arrow {
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
        width: 0;
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        /* Default arrow styles will be overridden by JavaScript */
    }

    /* Arrow positioning for below state is handled via JavaScript setAttribute */
</style> 