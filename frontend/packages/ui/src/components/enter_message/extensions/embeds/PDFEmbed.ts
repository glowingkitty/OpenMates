// src/components/MessageInput/extensions/embeds/PDFEmbed.ts
import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../../utils/editorHelpers';
import PDF from '../../in_message_previews/PDF.svelte'; // Import your Svelte component
import type { SvelteComponent } from 'svelte';

export interface PDFOptions {}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        pdfEmbed: {
            setPDFEmbed: (options: {src: string; filename: string; id: string}) => ReturnType
        }
    }
}

export const PDFEmbed = Node.create<PDFOptions>({
    name: 'pdfEmbed',
    group: 'inline',
    inline: true,
    selectable: true,
    draggable: true,

    addAttributes() {
        return {
            src: {
                default: null,
            },
            filename: {
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
                tag: 'div[data-pdf-embed]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-pdf-embed': true })];
    },

    addNodeView() {
        return ({ node, HTMLAttributes, getPos, editor }) => {
            const dom = document.createElement('div');
            dom.setAttribute('data-pdf-embed', 'true');

            let component: SvelteComponent | null = null;
            component = mountComponent(PDF, dom, {
                src: node.attrs.src,
                filename: node.attrs.filename,
                id: node.attrs.id,
            });

            return {
                dom,
                update: (updatedNode) => {
                    if (updatedNode.type !== this.type) {
						return false;
					}

					component?.$set({
						src: updatedNode.attrs.src,
						filename: updatedNode.attrs.filename,
						id: updatedNode.attrs.id
					});
                    return true;
                },
                destroy: () => {
                    component?.$destroy();
                    component = null;
                }
            };
        };
    },
    addCommands() {
        return {
            setPDFEmbed: options => ({ commands }) => {
                return commands.insertContent({
                    type: this.name,
                    attrs: options,
                })
            }
        }
    }
});