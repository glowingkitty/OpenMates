// frontend/packages/ui/src/components/enter_message/extensions/AIModelMentionNode.ts
//
// TipTap extension for AI model mentions.
// Displays a friendly model name to the user but serializes to @ai-model:id for backend.

import { Node, mergeAttributes } from '@tiptap/core';

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface AIModelMentionNodeOptions {}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        aiModelMention: {
            /**
             * Insert an AI model mention node
             * @param options.modelId - The full model ID (e.g., 'claude-opus-4-5-20251101')
             * @param options.displayName - The human-readable name (e.g., 'Claude 4.5 Opus')
             */
            setAIModelMention: (options: { modelId: string; displayName: string }) => ReturnType;
        };
    }
}

export const AIModelMentionNode = Node.create<AIModelMentionNodeOptions>({
    name: 'aiModelMention',
    group: 'inline',
    inline: true,
    selectable: true,
    draggable: true,
    atom: true, // Treat as a single unit for deletion

    addAttributes() {
        return {
            modelId: {
                default: null,
            },
            displayName: {
                default: null,
            },
        };
    },

    parseHTML() {
        return [
            {
                tag: 'span[data-type="ai-model-mention"]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return [
            'span',
            mergeAttributes(HTMLAttributes, {
                'data-type': 'ai-model-mention',
                'data-model-id': HTMLAttributes.modelId,
                class: 'ai-model-mention',
            }),
            `@${HTMLAttributes.displayName}`,
        ];
    },

    addCommands() {
        return {
            setAIModelMention: (options) => ({ commands }) => {
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

                if (node?.type.name === 'aiModelMention') {
                    const from = pos - node.nodeSize;
                    const to = pos;

                    // Delete any preceding space along with the mention
                    const beforeNode = editor.state.doc.textBetween(Math.max(0, from - 1), from);
                    const extraOffset = beforeNode === ' ' ? 1 : 0;

                    // Fully delete the mention node (and preceding space)
                    editor
                        .chain()
                        .focus()
                        .deleteRange({ from: from - extraOffset, to })
                        .run();

                    return true;
                }
                return false;
            },
        };
    },
});
