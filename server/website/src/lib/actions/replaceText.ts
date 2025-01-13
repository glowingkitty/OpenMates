/**
 * Svelte action that replaces instances of "OpenMates" with marked up version
 * Handles text nodes within regular elements and anchor tags
 * Logger used for debugging text replacements
 */
import { browser } from '$app/environment';
import { get } from 'svelte/store';
import { locale } from 'svelte-i18n';

export function replaceOpenMates(node: HTMLElement) {
    if (!browser) {
        return;
    }

    let currentLocale = get(locale);
    let isProcessing = false;

    function processNode(node: Node) {
        if (isProcessing) return;

        if (node.nodeType === Node.TEXT_NODE) {
            const text = node.textContent || '';
            if (text.includes('OpenMates')) {
                console.log('Processing OpenMates text node:', text);
                const container = document.createElement('div');
                const replacement = '<strong><mark>Open</mark><span style="color: var(--color-grey-100);">Mates</span></strong>';
                
                container.innerHTML = text.replace(/OpenMates/g, replacement);

                while (container.firstChild) {
                    node.parentNode?.insertBefore(container.firstChild, node);
                }
                node.parentNode?.removeChild(node);
            }
        } else {
            if (node.nodeName === 'MARK' ||
                node.nodeName === 'STRONG' ||
                (node.parentElement &&
                    (node.parentElement.nodeName === 'MARK' ||
                     node.parentElement.nodeName === 'STRONG'))) {
                return;
            }

            Array.from(node.childNodes).forEach(processNode);
        }
    }

    function processEntireNode() {
        isProcessing = true;
        try {
            processNode(node);
        } finally {
            isProcessing = false;
        }
    }

    setTimeout(processEntireNode, 0);

    const observer = new MutationObserver((mutations) => {
        const newLocale = get(locale);
        if (newLocale !== currentLocale) {
            currentLocale = newLocale;
            setTimeout(processEntireNode, 0);
        } else {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    processNode(node);
                });
            });
        }
    });

    observer.observe(node, {
        childList: true,
        subtree: true,
        characterData: true
    });

    return {
        destroy() {
            observer.disconnect();
        }
    };
}