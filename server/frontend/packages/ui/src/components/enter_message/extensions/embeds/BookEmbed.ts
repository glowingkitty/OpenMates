// src/components/MessageInput/extensions/embeds/BookEmbed.ts

import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../../utils/editorHelpers';
import Books from '../../in_message_previews/Books.svelte'; // Import your Svelte component
import type { SvelteComponent } from 'svelte';

export interface BookOptions {
}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        bookEmbed: {
            setBookEmbed: (options: { src: string; filename: string; id: string; bookname?: string; author?: string; coverUrl?: string;}) => ReturnType
        }
    }
}

export const BookEmbed = Node.create<BookOptions>({
    name: 'bookEmbed',
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
                default: () => crypto.randomUUID()
            },
            bookname: {
                default: null,
            },
            author: {
                default: null,
            },
            coverUrl: { // Added for book covers
              default: null
            }
        }
    },

    parseHTML() {
        return [
            {
                tag: 'div[data-book-embed]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-book-embed': true })];
    },

    addNodeView() {
        return ({ node, HTMLAttributes, getPos, editor }) => {
            const dom = document.createElement('div');
            dom.setAttribute('data-book-embed', 'true');

            let component: SvelteComponent | null = null;

            component = mountComponent(Books, dom, {
                src: node.attrs.src,
                filename: node.attrs.filename,
                id: node.attrs.id,
                bookname: node.attrs.bookname,
                author: node.attrs.author,
                coverUrl: node.attrs.coverUrl,
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
                        id: updatedNode.attrs.id,
                        bookname: updatedNode.attrs.bookname,
                        author: updatedNode.attrs.author,
                        coverUrl: updatedNode.attrs.coverUrl,
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
            setBookEmbed: options => ({ commands }) => {
                return commands.insertContent({
                    type: this.name,
                    attrs: options,
                })
            }
        }
    }
});