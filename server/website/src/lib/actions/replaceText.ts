/**
 * Svelte action that replaces instances of "OpenMates" with marked up version
 * Logger used for debugging text replacements
 */
import { browser } from '$app/environment';

export function replaceOpenMates(node: HTMLElement) {
    if (!browser) return;

    // Function to process text nodes
    function processNode(node: Node) {
        if (node.nodeType === Node.TEXT_NODE) {
            const text = node.textContent || '';
            if (text.includes('OpenMates')) {
                // Create a temporary container to hold our HTML
                const container = document.createElement('div');
                container.innerHTML = text.replace(/OpenMates/g, '<mark>Open</mark>Mates');

                // Replace the text node with the container's children
                while (container.firstChild) {
                    node.parentNode?.insertBefore(container.firstChild, node);
                }
                node.parentNode?.removeChild(node);
            }
        } else {
            // Skip processing if node is already a mark element or inside one
            if (node.nodeName === 'MARK' ||
                (node.parentElement && node.parentElement.nodeName === 'MARK')) {
                return;
            }

            // Process child nodes
            Array.from(node.childNodes).forEach(processNode);
        }
    }

    // Initial processing
    processNode(node);

    return {
        destroy() {
            // Cleanup if needed
        }
    };
} 