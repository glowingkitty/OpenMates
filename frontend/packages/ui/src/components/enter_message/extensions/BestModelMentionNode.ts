// frontend/packages/ui/src/components/enter_message/extensions/BestModelMentionNode.ts
//
// TipTap extension for "Best-of" model alias mentions.
// Displays a friendly name (e.g., "@Best-Coding") but serializes to @best-model:category for backend.
// The backend resolves the alias to the top-ranked model for that category from the leaderboard.

import { Node, mergeAttributes } from "@tiptap/core";

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface BestModelMentionNodeOptions {}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    bestModelMention: {
      /**
       * Insert a "Best-of" model alias mention node
       * @param options.category - The leaderboard category (e.g., 'overall', 'coding', 'math', 'creative')
       * @param options.displayName - The human-readable name (e.g., 'Best-Coding')
       */
      setBestModelMention: (options: {
        category: string;
        displayName: string;
      }) => ReturnType;
    };
  }
}

export const BestModelMentionNode = Node.create<BestModelMentionNodeOptions>({
  name: "bestModelMention",
  group: "inline",
  inline: true,
  selectable: true,
  draggable: true,
  atom: true, // Treat as a single unit for deletion

  // Return text for getText() calls - ensures mention contributes to text content
  renderText({ node }) {
    return `@${node.attrs.displayName}`;
  },

  addAttributes() {
    return {
      category: {
        default: "overall",
      },
      displayName: {
        default: "Best-Overall",
      },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'span[data-type="best-model-mention"]',
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-type": "best-model-mention",
        "data-category": HTMLAttributes.category,
        class: "best-model-mention",
      }),
      `@${HTMLAttributes.displayName}`,
    ];
  },

  addCommands() {
    return {
      setBestModelMention:
        (options) =>
        ({ commands }) => {
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

        if (node?.type.name === "bestModelMention") {
          const from = pos - node.nodeSize;
          const to = pos;

          // Delete any preceding space along with the mention
          const beforeNode = editor.state.doc.textBetween(
            Math.max(0, from - 1),
            from,
          );
          const extraOffset = beforeNode === " " ? 1 : 0;

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
