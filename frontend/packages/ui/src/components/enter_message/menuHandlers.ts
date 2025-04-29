import type { Editor } from '@tiptap/core';
// TODO: Find correct import for ProseMirrorNode type
// import type { Node as ProseMirrorNode } from '@tiptap/pm/model';
import { getLanguageFromFilename } from './utils'; // Assuming utils are accessible

// Define a type for the selected node state if not already defined globally
export interface SelectedNodeState {
    node: any; // TODO: Replace 'any' with ProseMirrorNode type
    pos: number;
}

/**
 * Handles the interaction (press/click) on an embed element.
 * Finds the corresponding node in the editor and prepares data for the menu.
 *
 * @returns An object containing menu position, embed ID, menu type, and selected node, or null if failed.
 */
export function handleEmbedInteraction(
    event: CustomEvent,
    editor: Editor,
    embedId: string
): { menuX: number; menuY: number; selectedEmbedId: string; menuType: 'default' | 'pdf' | 'web'; selectedNode: SelectedNodeState } | null {
    let foundNode: SelectedNodeState | null = null;

    // Find the node in the editor document based on the embedId attribute
    editor.state.doc.descendants((node: any, pos: number) => { // TODO: Use ProseMirrorNode type
        if (node.attrs?.id === embedId) {
            foundNode = { node, pos };
            return false; // Stop searching once found
        }
        return true; // Continue searching
    });

    if (!foundNode) {
        console.warn(`[MenuHandlers] Node not found for embedId: ${embedId}`);
        return null;
    }

    const element = document.getElementById(event.detail.elementId);
    if (!element) {
        console.warn(`[MenuHandlers] Element not found for embedId: ${embedId}`);
        return null;
    }

    const rect = element.getBoundingClientRect();
    const container = element.closest('.message-field'); // Adjust selector if needed
    if (!container) {
        console.warn(`[MenuHandlers] Container element not found.`);
        return null;
    }

    // Calculate menu position relative to the container
    const menuX = rect.left - container.getBoundingClientRect().left + (rect.width / 2);
    const menuY = rect.top - container.getBoundingClientRect().top;

    // Determine menu type based on the node
    let menuType: 'default' | 'pdf' | 'web' = 'default';
    if (foundNode.node.type.name === 'webPreview') {
        menuType = 'web';
    } else if (foundNode.node.attrs?.type === 'pdf') {
        menuType = 'pdf';
    }

    return {
        menuX,
        menuY,
        selectedEmbedId: embedId,
        menuType,
        selectedNode: foundNode
    };
}

/**
 * Handles actions triggered from the embed context menu.
 */
export async function handleMenuAction(
    action: string,
    selectedNodeState: SelectedNodeState | null,
    editor: Editor,
    dispatch: (type: string, detail?: any) => void,
    selectedEmbedId: string | null // Pass selectedEmbedId for UI feedback
): Promise<void> {
    if (!selectedNodeState) return;

    const { node, pos } = selectedNodeState;

    switch (action) {
        case 'delete':
            editor.chain().focus().deleteRange({ from: pos, to: pos + node.nodeSize }).run();
            break;

        case 'download':
            if (node.attrs.src) {
                const a = document.createElement('a');
                a.href = node.attrs.src;
                a.download = node.attrs.filename || 'download'; // Provide a default filename
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            } else {
                 console.warn("[MenuHandlers] Download failed: No src attribute found on node.", node);
            }
            break;

        case 'view':
            if (node.type.name === 'codeEmbed') {
                try {
                    const response = await fetch(node.attrs.src);
                    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                    const code = await response.text();
                    dispatch('codefullscreen', {
                        code,
                        filename: node.attrs.filename,
                        language: node.attrs.language || getLanguageFromFilename(node.attrs.filename)
                    });
                } catch (error) {
                    console.error('[MenuHandlers] Error loading code content for view:', error);
                    alert('Failed to load code content.'); // Inform user
                }
            } else {
                // Handle web previews (YouTube or generic URLs) and other file types
                const urlToOpen = node.attrs.isYouTube
                    ? `https://www.youtube.com/watch?v=${node.attrs.videoId}`
                    : (node.attrs.url || node.attrs.src); // Use url for webPreview, src for others

                if (urlToOpen) {
                    window.open(urlToOpen, '_blank', 'noopener,noreferrer');
                } else {
                     console.warn("[MenuHandlers] View failed: No URL or src attribute found.", node);
                }
            }
            break;

        case 'copy':
            const urlToCopy = node.attrs.isYouTube
                ? `https://www.youtube.com/watch?v=${node.attrs.videoId}`
                : (node.attrs.url || node.attrs.src);

            if (urlToCopy) {
                try {
                    await navigator.clipboard.writeText(urlToCopy);
                    // Provide visual feedback
                    const element = document.getElementById(`embed-${selectedEmbedId}`); // Use the passed embedId
                    if (element) {
                        element.classList.add('show-copied'); // Add class for feedback
                        setTimeout(() => element.classList.remove('show-copied'), 2000); // Remove after 2s
                    }
                } catch (err) {
                    console.error('[MenuHandlers] Failed to copy URL:', err);
                    alert('Failed to copy URL to clipboard.'); // Inform user
                }
            } else {
                 console.warn("[MenuHandlers] Copy failed: No URL or src attribute found.", node);
            }
            break;
    }
}