import { mount, unmount } from 'svelte';
import Tooltip from '../components/common/Tooltip.svelte';

/**
 * Svelte 5 compatible tooltip action
 * Creates a tooltip component for elements with aria-label attribute
 * Skips tooltip creation on touch devices for better UX
 */
export function tooltip(node: HTMLElement) {
    // Browser-only guard for SSR compatibility
    const browser = typeof window !== 'undefined';
    
    // Return no-op action for SSR or when conditions aren't met
    if (!browser || !node.getAttribute('aria-label')) {
        return {
            destroy() {
                // No-op for SSR or when no aria-label
            }
        };
    }
    
    // Check if device is touch-enabled
    const isTouchDevice = ('ontouchstart' in window) || 
        (navigator.maxTouchPoints > 0) || 
        // @ts-ignore
        (navigator.msMaxTouchPoints > 0);
    
    // Don't initialize tooltip on touch devices
    if (isTouchDevice) {
        console.debug('Skipping tooltip creation on touch device'); // Debug log
        return {
            destroy() {
                // No-op for touch devices
            }
        };
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