// frontend/packages/ui/src/components/enter_message/extensions/GenericMentionNode.ts
//
// Generic mention node for skills, focus modes, and settings/memories.
// Displays hyphenated name (e.g., "@Code-Get-Docs") but serializes to backend syntax.

import { Node, mergeAttributes } from "@tiptap/core";

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface GenericMentionNodeOptions {}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    genericMention: {
      setGenericMention: (options: {
        mentionType: "skill" | "focus_mode" | "settings_memory";
        displayName: string;
        mentionSyntax: string;
        /** Gradient start color from app config */
        colorStart?: string;
        /** Gradient end color from app config */
        colorEnd?: string;
      }) => ReturnType;
    };
  }
}

export const GenericMentionNode = Node.create<GenericMentionNodeOptions>({
  name: "genericMention",
  group: "inline",
  inline: true,
  atom: true, // Treated as single unit for selection/deletion
  selectable: true,
  draggable: true,

  // Return text for getText() calls - ensures mention contributes to text content
  // This is critical for NewChatSuggestions filtering to work correctly
  renderText({ node }) {
    return `@${node.attrs.displayName}`;
  },

  addAttributes() {
    return {
      mentionType: {
        default: "skill",
      },
      displayName: {
        default: "",
      },
      mentionSyntax: {
        default: "",
      },
      colorStart: {
        default: null,
      },
      colorEnd: {
        default: null,
      },
    };
  },

  // Markdown serialization - converts node to backend syntax
  addStorage() {
    return {
      markdown: {
        serialize: (
          state: { write: (text: string) => void },
          node: { attrs: { mentionSyntax: string } },
        ) => {
          // Serialize to backend syntax: @skill:app:id, @focus:app:id, @memory:app:id:type
          state.write(node.attrs.mentionSyntax);
        },
      },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'span[data-type="generic-mention"]',
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    // Determine CSS class based on mention type
    const typeClass = `mention-${HTMLAttributes.mentionType.replace("_", "-")}`;

    // Apply the app's custom gradient colors via inline CSS custom properties
    // These are used by the .generic-mention CSS rule in MessageInput.styles.css
    const style =
      HTMLAttributes.colorStart && HTMLAttributes.colorEnd
        ? `--mention-color-start: ${HTMLAttributes.colorStart}; --mention-color-end: ${HTMLAttributes.colorEnd};`
        : "";

    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-type": "generic-mention",
        "data-mention-type": HTMLAttributes.mentionType,
        "data-display-name": HTMLAttributes.displayName,
        "data-mention-syntax": HTMLAttributes.mentionSyntax,
        class: `generic-mention ${typeClass}`,
        style: style,
        contenteditable: "false",
      }),
      `@${HTMLAttributes.displayName}`,
    ];
  },

  addCommands() {
    return {
      setGenericMention:
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

        if (node?.type.name === "genericMention") {
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
