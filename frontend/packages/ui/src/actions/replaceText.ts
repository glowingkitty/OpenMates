/**
 * Svelte action that replaces instances of "OpenMates" with marked up version
 * Handles text nodes within regular elements and anchor tags
 */
import { get } from 'svelte/store';
import { locale, waitLocale } from 'svelte-i18n';

// Browser check - this is a client-side only action
const browser = typeof window !== 'undefined';

export function replaceOpenMates(node: HTMLElement) {
    // Return a no-op action for SSR - must return an object with destroy method
    if (!browser) {
        return {
            destroy() {
                // No-op for SSR
            }
        };
    }

    let isProcessing = false;
    let observer: MutationObserver | null = null;
    let currentLocale = get(locale);

    function processNode(node: Node) {
        if (node.nodeType === Node.TEXT_NODE) {
            const text = node.textContent || '';
            if (text.includes('OpenMates')) {
                // Don't process if we're in English mode and there's a translation available
                if (currentLocale === 'en' && node.parentElement?.hasAttribute('data-i18n')) {
                    return;
                }
                
                // Skip if we're inside a suggestion item (new chat or follow-up suggestions)
                if (node.parentElement?.closest('.suggestion-item')) {
                    return;
                }
                
                // Skip if we're inside a suggestions container
                if (node.parentElement?.closest('.suggestions-container')) {
                    return;
                }

                const container = document.createElement('div');
                const replacement = '<strong><mark>Open</mark><span style="color: var(--color-grey-100);">Mates</span></strong>';
                container.innerHTML = text.replace(/OpenMates/g, replacement);

                while (container.firstChild) {
                    node.parentNode?.insertBefore(container.firstChild, node);
                }
                node.parentNode?.removeChild(node);
            }
        } else {
            // Skip if we're inside a mark or strong tag already
            if (node.nodeName === 'MARK' ||
                node.nodeName === 'STRONG' ||
                (node.parentElement &&
                    (node.parentElement.nodeName === 'MARK' ||
                     node.parentElement.nodeName === 'STRONG'))) {
                return;
            }
            
            // Skip if we're inside a suggestion item or container
            if (node.nodeName === 'BUTTON' && (node as HTMLElement).classList.contains('suggestion-item')) {
                return;
            }

            Array.from(node.childNodes).forEach(processNode);
        }
    }

    function processEntireNode() {
        if (isProcessing) return;
        isProcessing = true;
        try {
            processNode(node);
        } finally {
            isProcessing = false;
        }
    }

    // Subscribe to locale changes
    const unsubscribe = locale.subscribe(value => {
        currentLocale = value;
        processEntireNode();
    });

    // Set up mutation observer to handle dynamic text changes
    observer = new MutationObserver(() => {
        requestAnimationFrame(() => {
            processEntireNode();
        });
    });

    // Start observing
    observer.observe(node, {
        childList: true,
        characterData: true,
        subtree: true
    });

    return {
        destroy() {
            observer?.disconnect();
            unsubscribe();
        }
    };
}