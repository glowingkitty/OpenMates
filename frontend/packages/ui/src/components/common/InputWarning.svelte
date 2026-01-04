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
    
    // Track ancestors for cleanup of event listeners
    let scrollableAncestors: HTMLElement[] = [];
    let transitionAncestors: HTMLElement[] = [];
    
    /**
     * Updates the warning position to be above the target element.
     * Uses getBoundingClientRect() to get the visual position relative to viewport,
     * which works correctly with position: fixed.
     */
    function updatePosition() {
        if (!target) return;
        const rect = target.getBoundingClientRect();
        position = {
            top: rect.top - 8,
            left: rect.left + (rect.width / 2)
        };
    }
    
    /**
     * Finds all scrollable ancestor elements of the target.
     * This is needed because the warning uses position: fixed, but the target
     * might be inside a scrollable container (e.g., login-content on mobile).
     * We need to listen to scroll events on these containers to update position.
     * @param element - The target element to start searching from
     * @returns Array of scrollable ancestor elements
     */
    function getScrollableAncestors(element: HTMLElement): HTMLElement[] {
        const ancestors: HTMLElement[] = [];
        let parent = element.parentElement;
        
        while (parent) {
            const style = getComputedStyle(parent);
            const overflowY = style.overflowY;
            const overflowX = style.overflowX;
            
            // Check if this element is scrollable
            // scrollable if overflow is 'auto', 'scroll', or 'overlay'
            if (
                overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay' ||
                overflowX === 'auto' || overflowX === 'scroll' || overflowX === 'overlay'
            ) {
                ancestors.push(parent);
            }
            
            parent = parent.parentElement;
        }
        
        return ancestors;
    }
    
    /**
     * Gets all ancestor elements that might have CSS transitions/transforms.
     * CSS transforms on ancestors break position: fixed positioning.
     * When a transition ends on an ancestor (like scale animation completing),
     * we need to recalculate position.
     * @param element - The target element to start searching from
     * @returns Array of ancestor elements (up to a reasonable limit)
     */
    function getTransitionAncestors(element: HTMLElement): HTMLElement[] {
        const ancestors: HTMLElement[] = [];
        let parent = element.parentElement;
        let depth = 0;
        const maxDepth = 10; // Don't traverse too far up
        
        while (parent && depth < maxDepth) {
            ancestors.push(parent);
            parent = parent.parentElement;
            depth++;
        }
        
        return ancestors;
    }
    
    /**
     * Sets up scroll listeners on all scrollable ancestors.
     * Cleans up any existing listeners first.
     */
    function setupScrollListeners() {
        // Clean up existing listeners
        cleanupScrollListeners();
        
        if (!target) return;
        
        // Find all scrollable ancestors
        scrollableAncestors = getScrollableAncestors(target);
        
        // Add scroll listeners to each scrollable ancestor
        scrollableAncestors.forEach(ancestor => {
            ancestor.addEventListener('scroll', updatePosition, { passive: true });
        });
    }
    
    /**
     * Sets up transitionend listeners on ancestor elements.
     * This handles the case where ancestors have CSS transforms during animations
     * (like Svelte's in:scale transition on .login-box).
     * When transform animations complete, position: fixed works correctly again,
     * so we recalculate position.
     */
    function setupTransitionListeners() {
        cleanupTransitionListeners();
        
        if (!target) return;
        
        transitionAncestors = getTransitionAncestors(target);
        
        transitionAncestors.forEach(ancestor => {
            ancestor.addEventListener('transitionend', updatePosition, { passive: true });
            ancestor.addEventListener('animationend', updatePosition, { passive: true });
        });
    }
    
    /**
     * Removes scroll listeners from all tracked scrollable ancestors.
     */
    function cleanupScrollListeners() {
        scrollableAncestors.forEach(ancestor => {
            ancestor.removeEventListener('scroll', updatePosition);
        });
        scrollableAncestors = [];
    }
    
    /**
     * Removes transition/animation listeners from all tracked ancestors.
     */
    function cleanupTransitionListeners() {
        transitionAncestors.forEach(ancestor => {
            ancestor.removeEventListener('transitionend', updatePosition);
            ancestor.removeEventListener('animationend', updatePosition);
        });
        transitionAncestors = [];
    }
    
    onMount(() => {
        // Initial position update
        updatePosition();
        
        // Set up scroll listeners on scrollable ancestors
        setupScrollListeners();
        
        // Set up transition/animation listeners on ancestors
        // This handles cases where ancestors have CSS transforms during animations
        // (e.g., Svelte's in:scale transition on .login-box that breaks position: fixed)
        setupTransitionListeners();
        
        // Also listen to window scroll and resize
        window.addEventListener('scroll', updatePosition, { passive: true });
        window.addEventListener('resize', updatePosition, { passive: true });
        
        // CRITICAL: Schedule additional position updates to handle CSS transform issues
        // When ancestors have transforms (like scale animations), position: fixed
        // positions relative to the transformed ancestor, not the viewport.
        // We schedule updates at common animation completion times to ensure
        // position is recalculated after transforms are removed.
        const delayedUpdates = [
            setTimeout(updatePosition, 100),  // After short animations
            setTimeout(updatePosition, 300),  // After medium animations
            setTimeout(updatePosition, 500),  // After longer animations (like login-box scale)
        ];
        
        // Set auto-hide timer
        if (autoHideDelay > 0) {
            hideTimer = setTimeout(() => {
                visible = false;
            }, autoHideDelay);
        }
        
        return () => {
            cleanupScrollListeners();
            cleanupTransitionListeners();
            window.removeEventListener('scroll', updatePosition);
            window.removeEventListener('resize', updatePosition);
            delayedUpdates.forEach(clearTimeout);
            if (hideTimer) clearTimeout(hideTimer);
        };
    });
    
    // Watch for target changes using Svelte 5 runes
    // When target changes, re-setup all listeners and update position
    $effect(() => {
        if (target) {
            setupScrollListeners();
            setupTransitionListeners();
            updatePosition();
        }
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
