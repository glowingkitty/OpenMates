import Tooltip from '../components/common/Tooltip.svelte';

export function tooltip(node: HTMLElement) {
    // Only create tooltip if element has aria-label
    if (!node.getAttribute('aria-label')) return;

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