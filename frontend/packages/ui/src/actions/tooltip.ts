import { mount, unmount } from 'svelte';
import Tooltip from '../components/common/Tooltip.svelte';

/**
 * Svelte 5 compatible tooltip action
 * Creates a tooltip component for elements with aria-label attribute
 * Skips tooltip creation on touch devices for better UX
 */
export function tooltip(node: HTMLElement) {
    // Only create tooltip if element has aria-label and not on touch devices
    if (!node.getAttribute('aria-label')) return;
    
    // Check if device is touch-enabled
    const isTouchDevice = ('ontouchstart' in window) || 
        (navigator.maxTouchPoints > 0) || 
        // @ts-ignore
        (navigator.msMaxTouchPoints > 0);
    
    // Don't initialize tooltip on touch devices
    if (isTouchDevice) {
        console.debug('Skipping tooltip creation on touch device'); // Debug log
        return;
    }

    // Create tooltip component instance using Svelte 5 mount API
    const tooltip = mount(Tooltip, {
        target: document.body,
        props: {
            element: node
        }
    });

    // Return cleanup function for Svelte 5 compatibility
    return {
        destroy() {
            // Use Svelte 5 unmount function to properly clean up
            if (tooltip) {
                unmount(tooltip);
            }
        }
    };
} 