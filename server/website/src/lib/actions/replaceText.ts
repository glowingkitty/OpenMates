/**
 * Svelte action that replaces instances of "OpenMates" with marked up version
 * Handles text nodes within regular elements and anchor tags
 * Logger used for debugging text replacements
 */
import { browser } from '$app/environment';

export function replaceOpenMates(node: HTMLElement) {
    if (!browser) {
        return;
    }

    // Create MutationObserver to watch for DOM changes
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            // Process new nodes
            mutation.addedNodes.forEach((node) => {
                if (node.nodeType === Node.ELEMENT_NODE) {
                    processNode(node);
                }
            });
        });
    });

    // Function to process text nodes
    function processNode(node: Node) {
        if (node.nodeType === Node.TEXT_NODE) {
            const text = node.textContent || '';
            if (text.includes('OpenMates')) {

                // Create a temporary container to hold our HTML
                const container = document.createElement('div');

                // Check if parent is an anchor tag to preserve the link functionality
                const isInAnchor = node.parentElement?.nodeName === 'A';

                if (isInAnchor) {
                    // For text in anchor tags, preserve link functionality but ensure Mates is black
                    container.innerHTML = text.replace(
                        /OpenMates/g,
                        '<span><mark>Open</mark><span style="color: black;">Mates</span></span>'
                    );
                } else {
                    container.innerHTML = text.replace(
                        /OpenMates/g,
                        '<strong><mark>Open</mark><span style="color: black;">Mates</span></strong>'
                    );
                }

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

    // Start observing the entire document for changes
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    return {
        destroy() {
            // Cleanup: disconnect the observer when the action is destroyed
            observer.disconnect();
        }
    };
}