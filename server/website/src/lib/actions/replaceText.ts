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
                container.innerHTML = text.replace(
                    /OpenMates/g, 
                    '<strong><mark>Open</mark><span style="color: black;">Mates</span></strong>'
                );

                // Replace the text node with the container's children
                while (container.firstChild) {
                    node.parentNode?.insertBefore(container.firstChild, node);
                }
                node.parentNode?.removeChild(node);
            }
        } else {
            // Skip processing if node is already styled or inside styled elements
            if (node.nodeName === 'MARK' || 
                node.nodeName === 'STRONG' ||
                (node.parentElement && 
                    (node.parentElement.nodeName === 'MARK' || 
                     node.parentElement.nodeName === 'STRONG'))) {
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