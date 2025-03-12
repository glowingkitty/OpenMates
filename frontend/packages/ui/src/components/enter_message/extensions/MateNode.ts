// src/components/MessageInput/extensions/MateNode.ts
import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../utils/editorHelpers';

export interface MateNodeOptions {}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        mate: {
            setMate: (options: { name: string; id: string }) => ReturnType;
        };
    }
}
export const MateNode = Node.create<MateNodeOptions>({
    name: 'mate',
    group: 'inline',
    inline: true,
    selectable: true,
    draggable: true,

    addAttributes() {
        return {
            name: {
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
                tag: 'span[data-type="mate"]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        const elementId = `mate-${HTMLAttributes.id}`;
        return [
            'span',
            mergeAttributes(HTMLAttributes, {
                'data-type': 'mate',
                'data-id': HTMLAttributes.id,
                'data-name': HTMLAttributes.name,
                id: elementId,
                class: 'mate-mention',
                // Removed onclick, since we handle it now in the main component
            }),
            ['span', { class: 'at-symbol' }, '@'],
            [
                'div',
                {
                    class: `mate-profile mate-profile-small ${HTMLAttributes.name}`,
                },
            ],
        ];
    },

    addCommands() {
        return {
            setMate: (options) => ({ commands }) => {
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
                const { empty, $anchor } = editor.state.selection;
                if (!empty) return false;

                const pos = $anchor.pos;
                const node = editor.state.doc.nodeAt(pos - 1);

                if (node?.type.name === 'mate') {
                    const name = node.attrs.name;
                    const from = pos - node.nodeSize;
                    const to = pos;

                    // First delete any preceding space
                    const beforeNode = editor.state.doc.textBetween(Math.max(0, from - 1), from);
                    const extraOffset = beforeNode === ' ' ? 1 : 0;

                    editor
                        .chain()
                        .focus()
                        .deleteRange({ from: from - extraOffset, to })
                        .insertContent(`@${name}`)
                        .run();

                    return true;
                }
                return false;
            },
        };
    },
    // No addNodeView needed, as we don't need a svelte component for this
});