// src/components/MessageInput/extensions/WebPreview.ts
import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../utils/editorHelpers';
import Web from '../in_message_previews/Web.svelte';
import type { SvelteComponent } from 'svelte';

export interface WebPreviewOptions {}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        webPreview: {
            setWebPreview: (options: { url: string; id: string }) => ReturnType;
        };
    }
}

export const WebPreview = Node.create<WebPreviewOptions>({
    name: 'webPreview',
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
                tag: 'div[data-web-preview]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-web-preview': true })];
    },

    addNodeView() {
        return ({ node, HTMLAttributes, getPos, editor }) => {
            const dom = document.createElement('div');
            dom.setAttribute('data-web-preview', 'true');

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
            setWebPreview: (options) => ({ commands }) => {
                return commands.insertContent({
                    type: this.name,
                    attrs: options,
                });
            },
        };
    },
    addKeyboardShortcuts() {
        return {
            Backspace: ({ editor }) => {
                const { empty, $anchor } = editor.state.selection
                if (!empty) return false

                const pos = $anchor.pos
                const node = editor.state.doc.nodeAt(pos - 1)

                if (node?.type.name === 'webPreview') {
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