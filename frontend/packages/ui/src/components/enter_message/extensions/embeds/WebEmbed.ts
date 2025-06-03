// src/components/MessageInput/extensions/embeds/WebEmbed.ts
import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../../utils/editorHelpers'; // Adjusted path
import Web from '../../in_message_previews/Web.svelte'; // Adjusted path
import type { SvelteComponent } from 'svelte';

export interface WebEmbedOptions {}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        webEmbed: { // Renamed command
            setWebEmbed: (options: { url: string; id: string }) => ReturnType; // Renamed command method
        };
    }
}

export const WebEmbed = Node.create<WebEmbedOptions>({ // Renamed class
    name: 'webEmbed', // Renamed node name
    group: 'inline',
    inline: true,
    selectable: true,
    draggable: true,

    addAttributes() {
        return {
            url: {
                default: null,
            },
            id: {
                default: () => crypto.randomUUID(),
            },
        };
    },

    parseHTML() {
        return [
            {
                tag: 'div[data-web-embed]', // Changed data attribute
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-web-embed': true })]; // Changed data attribute
    },

    addNodeView() {
        return ({ node, HTMLAttributes, getPos, editor }) => {
            const dom = document.createElement('div');
            dom.setAttribute('data-web-embed', 'true'); // Changed data attribute

            let component: SvelteComponent | null = null;
            component = mountComponent(Web, dom, {
                url: node.attrs.url,
                id: node.attrs.id,
            });

            return {
                dom,
                update: (updatedNode) => {
                    if (updatedNode.type !== this.type) {
                        return false;
                    }
                    component?.$set({
                        url: updatedNode.attrs.url,
                        id: updatedNode.attrs.id,
                    });
                    return true;
                },
                destroy: () => {
                    component?.$destroy();
                    component = null;
                },
            };
        };
    },
    addCommands() {
        return {
            setWebEmbed: (options) => ({ commands }) => { // Renamed command method
                return commands.insertContent({
                    type: this.name,
                    attrs: options,
                });
            },
        };
    },
    addKeyboardShortcuts() { // Preserving this functionality
        return {
            Backspace: ({ editor }) => {
                const { empty, $anchor } = editor.state.selection
                if (!empty) return false

                const pos = $anchor.pos
                const node = editor.state.doc.nodeAt(pos - 1)

                if (node?.type.name === this.name) { // Use this.name
                    const url = node.attrs.url
                    const from = pos - node.nodeSize
                    const to = pos

                    // First delete any preceding space
                    const beforeNode = editor.state.doc.textBetween(Math.max(0, from - 1), from)
                    const extraOffset = beforeNode === ' ' ? 1 : 0

                    editor
                        .chain()
                        .focus()
                        .deleteRange({ from: from - extraOffset, to })
                        .insertContent(url)
                        .run()

                    return true;
                }
                return false;
            }
        }
    },
});
