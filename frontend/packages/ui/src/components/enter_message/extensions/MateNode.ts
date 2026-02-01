// src/components/MessageInput/extensions/MateNode.ts
import { Node, mergeAttributes } from "@tiptap/core";

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface MateNodeOptions {}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    mate: {
      setMate: (options: {
        name: string;
        displayName: string;
        id: string;
        colorStart?: string;
        colorEnd?: string;
      }) => ReturnType;
    };
  }
}
export const MateNode = Node.create<MateNodeOptions>({
  name: "mate",
  group: "inline",
  inline: true,
  selectable: true,
  draggable: true,
  atom: true, // Treat as single unit for selection/deletion

  // Return text for getText() calls - ensures mention contributes to text content
  // This is critical for NewChatSuggestions filtering to work correctly
  renderText({ node }) {
    return `@${node.attrs.displayName || node.attrs.name}`;
  },

  addAttributes() {
    return {
      name: {
        default: null,
      },
      displayName: {
        default: null,
      },
      id: {
        default: () => crypto.randomUUID(),
      },
      colorStart: {
        default: null,
      },
      colorEnd: {
        default: null,
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
    // Display the mate mention as "@DisplayName" (e.g., "@Sophia")
    // This matches the AI model mention format for consistency
    // Apply the mate's custom gradient colors via inline CSS custom properties
    const style =
      HTMLAttributes.colorStart && HTMLAttributes.colorEnd
        ? `--mate-color-start: ${HTMLAttributes.colorStart}; --mate-color-end: ${HTMLAttributes.colorEnd};`
        : "";
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-type": "mate",
        "data-id": HTMLAttributes.id,
        "data-name": HTMLAttributes.name,
        id: elementId,
        class: "mate-mention",
        style: style,
        // Removed onclick, since we handle it now in the main component
      }),
      `@${HTMLAttributes.displayName || HTMLAttributes.name}`,
    ];
  },

  addCommands() {
    return {
      setMate:
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

        if (node?.type.name === "mate") {
          const name = node.attrs.name;
          const from = pos - node.nodeSize;
          const to = pos;

          // First delete any preceding space
          const beforeNode = editor.state.doc.textBetween(
            Math.max(0, from - 1),
            from,
          );
          const extraOffset = beforeNode === " " ? 1 : 0;

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
