// src/components/MessageInput/extensions/embeds/TextEmbed.ts
import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../../utils/editorHelpers';
import Text from '../../in_message_previews/Text.svelte'; // Import your Svelte component
import type { SvelteComponent } from 'svelte';

export interface TextOptions {}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        textEmbed: {
            setTextEmbed: (options: {content: string; id: string;}) => ReturnType
        }
    }
}

export const TextEmbed = Node.create<TextOptions>({
    name: 'textEmbed',
    group: 'inline',
    inline: true,
    selectable: true,
    draggable: true,

    addAttributes() {
        return {
            content: {
                default: null,
            },
            id: {
                default: () => crypto.randomUUID()
            }
        }
    },

    parseHTML() {
        return [
            {
                tag: 'div[data-text-embed]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-text-embed': true })];
    },

    addNodeView() {
        return ({ node, HTMLAttributes, getPos, editor }) => {
            const dom = document.createElement('div');
            dom.setAttribute('data-text-embed', 'true');

            let component: SvelteComponent | null = null;

            component = mountComponent(Text, dom, {
                content: node.attrs.content,
                id: node.attrs.id
            });

            return {
                dom,
                update: (updatedNode) => {
                    if (updatedNode.type !== this.type) {
                        return false;
                    }
                    component?.$set({
                        content: updatedNode.attrs.content,
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
        return{
            setTextEmbed: options => ({commands}) => {
                return commands.insertContent({
                    type: this.name,
                    attrs: options
                })
            }
        }
    }
});