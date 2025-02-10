import Tooltip from '../components/common/Tooltip.svelte';

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
        console.log('Skipping tooltip creation on touch device'); // Debug log
        return;
    }

    const tooltip = new Tooltip({
        target: document.body,
        props: {
            element: node
        }
    });

    return {
        destroy() {
            tooltip.$destroy();
        }
    };
} 