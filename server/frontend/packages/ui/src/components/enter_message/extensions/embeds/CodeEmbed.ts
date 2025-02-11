// src/components/MessageInput/extensions/embeds/CodeEmbed.ts

import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../../utils/editorHelpers';
import Code from '../../in_message_previews/Code.svelte'; // Import your Svelte component
import type { SvelteComponent } from 'svelte';

export interface CodeOptions {}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        codeEmbed: {
            setCodeEmbed: (options: {src: string; filename: string; id: string; language?: string; content?:string}) => ReturnType
        }
    }
}

export const CodeEmbed = Node.create<CodeOptions>({
    name: 'codeEmbed',
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
            language: {
                default: null,
            },
            content: { //for text directly added
                default: null,
            }
        };
    },

    parseHTML() {
        return [
            {
                tag: 'div[data-code-embed]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-code-embed': true })];
    },

    addNodeView() {
        return ({ node, HTMLAttributes, getPos, editor }) => {
            const dom = document.createElement('div');
            dom.setAttribute('data-code-embed', 'true');

            let component: SvelteComponent | null = null;
            component = mountComponent(Code, dom, {
                src: node.attrs.src,
                filename: node.attrs.filename,
                id: node.attrs.id,
                language: node.attrs.language,
                content: node.attrs.content,
            });

            // Fixed event listener type
            dom.addEventListener('codefullscreen', ((event: Event) => {
                const customEvent = new CustomEvent('codefullscreen', {
                    detail: (event as CustomEvent).detail,
                    bubbles: true,
                    composed: true
                });
                dom.dispatchEvent(customEvent);
            }) as EventListener);

            return {
                dom,
                update: (updatedNode) => {
                    if (updatedNode.type !== this.type) {
                        return false;
                    }

                    component?.$set({
                        src: updatedNode.attrs.src,
                        filename: updatedNode.attrs.filename,
                        id: updatedNode.attrs.id,
                        language: updatedNode.attrs.language,
                        content: updatedNode.attrs.content
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
            setCodeEmbed: options => ({ commands }) => {
                return commands.insertContent({
                    type: this.name,
                    attrs: options,
                })
            }
        }
    }
});
