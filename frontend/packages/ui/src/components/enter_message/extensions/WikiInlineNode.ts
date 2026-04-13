// frontend/packages/ui/src/components/enter_message/extensions/WikiInlineNode.ts
//
// TipTap inline atom node for Wikipedia topic links injected by the post-processor.
//
// The AI post-processor identifies notable topics in the assistant's response,
// validates them against Wikipedia's batch API, and stores confirmed matches
// on the chat. parse_message.ts scans assistant message text for matching phrases
// and converts them to wikiInline atom nodes.
//
// The node is read-only and atom (treated as a single unit). On click it
// dispatches a document-level "wikifullscreen" CustomEvent so ActiveChat can
// open the Wikipedia fullscreen panel and fetch the article summary on-demand.
//
// Visual design:
//   - Small (20 px) circular Wikipedia blue badge with white "W" letter
//   - Followed by the display text styled as a blue link

import { Node, mergeAttributes } from "@tiptap/core";
import { mount, unmount } from "svelte";
import WikiInlineLink from "../../embeds/wiki/WikiInlineLink.svelte";

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface WikiInlineNodeOptions {}

export const WikiInlineNode = Node.create<WikiInlineNodeOptions>({
  name: "wikiInline",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  draggable: false,

  // renderText so the node contributes to plain-text extraction (e.g. copy)
  renderText({ node }) {
    return node.attrs.displayText || "";
  },

  addAttributes() {
    return {
      /** The matched topic phrase as it appears in the message text */
      displayText: { default: "" },
      /** Canonical Wikipedia article title (e.g. "Albert_Einstein") */
      wikiTitle: { default: "" },
      /** Wikidata QID (e.g. "Q937") — may be null */
      wikidataId: { default: null },
      /** Thumbnail URL from Wikipedia validation — may be null */
      thumbnailUrl: { default: null },
      /** Short description from Wikipedia/Wikidata — may be null */
      description: { default: null },
    };
  },

  parseHTML() {
    return [{ tag: 'span[data-type="wiki-inline"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-type": "wiki-inline",
        "data-wiki-title": HTMLAttributes.wikiTitle,
        "data-display-text": HTMLAttributes.displayText,
        class: "wiki-inline-node",
        contenteditable: "false",
      }),
      HTMLAttributes.displayText || "",
    ];
  },

  // Vanilla DOM NodeView using Svelte 5 mount/unmount
  addNodeView() {
    return ({ node }) => {
      const dom = document.createElement("span");
      dom.setAttribute("data-type", "wiki-inline");
      dom.setAttribute("contenteditable", "false");
      dom.classList.add("wiki-inline-node");

      let svelteInstance: Record<string, unknown> | null = null;
      try {
        svelteInstance = mount(WikiInlineLink, {
          target: dom,
          props: {
            displayText: node.attrs.displayText as string,
            wikiTitle: node.attrs.wikiTitle as string,
            wikidataId: node.attrs.wikidataId as string | null,
            thumbnailUrl: node.attrs.thumbnailUrl as string | null,
            description: node.attrs.description as string | null,
          },
        }) as Record<string, unknown>;
      } catch (err) {
        console.error("[WikiInlineNode] Failed to mount WikiInlineLink:", err);
        dom.textContent = node.attrs.displayText || "";
      }

      let currentAttrs = { ...node.attrs };

      return {
        dom,
        update(updatedNode) {
          if (updatedNode.type.name !== "wikiInline") return false;

          const newAttrs = updatedNode.attrs;
          if (
            newAttrs.displayText === currentAttrs.displayText &&
            newAttrs.wikiTitle === currentAttrs.wikiTitle &&
            newAttrs.wikidataId === currentAttrs.wikidataId
          ) {
            return true; // No DOM changes needed
          }

          currentAttrs = { ...newAttrs };

          if (svelteInstance) {
            try { unmount(svelteInstance); } catch { /* ignore */ }
          }
          dom.innerHTML = "";
          try {
            svelteInstance = mount(WikiInlineLink, {
              target: dom,
              props: {
                displayText: newAttrs.displayText as string,
                wikiTitle: newAttrs.wikiTitle as string,
                wikidataId: newAttrs.wikidataId as string | null,
                thumbnailUrl: newAttrs.thumbnailUrl as string | null,
                description: newAttrs.description as string | null,
              },
            }) as Record<string, unknown>;
          } catch (err) {
            console.error("[WikiInlineNode] Failed to re-mount WikiInlineLink:", err);
            dom.textContent = newAttrs.displayText || "";
          }
          return true;
        },
        destroy() {
          if (svelteInstance) {
            try { unmount(svelteInstance); } catch { /* ignore */ }
            svelteInstance = null;
          }
        },
      };
    };
  },
});
