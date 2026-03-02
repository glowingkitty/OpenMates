// frontend/packages/ui/src/components/enter_message/extensions/EmbedInlineNode.ts
//
// TipTap inline atom node for inline embed references produced by the LLM.
//
// The LLM writes [display text](embed:some-ref-k8D) in its response.
// parse_message.ts / the post-processor in parse_message.ts converts those
// Markdown link nodes (href starts with "embed:") into `embedInline` nodes
// with the attributes below.
//
// The node is read-only and atom (treated as a single unit).  On click it
// dispatches a document-level "embedfullscreen" CustomEvent (same pattern as
// AppSkillUseRenderer / GroupRenderer) so ActiveChat can open the fullscreen
// panel without needing a direct callback prop.
//
// Visual design:
//   • Small (20 px) circular gradient badge showing the app icon
//   • Followed by the display text styled as a gradient link
//
// Architecture note:
//   embed_ref is the LLM-facing short slug (e.g. "ryanair-0600-k8D").
//   embed_id is the UUID used internally.  The in-memory embedRefToIdIndex in
//   embedStore maps ref → id.  The EmbedInlineLink component resolves the id
//   at render time and passes it to the fullscreen event.

import { Node, mergeAttributes } from "@tiptap/core";
import { mount, unmount } from "svelte";
import EmbedInlineLink from "../../embeds/EmbedInlineLink.svelte";

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface EmbedInlineNodeOptions {}

export const EmbedInlineNode = Node.create<EmbedInlineNodeOptions>({
  name: "embedInline",
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
      /** Short descriptive slug from embed_ref (e.g. "ryanair-0600-k8D") */
      embedRef: {
        default: "",
      },
      /** UUID of the embed — may be null if the index hasn't been populated yet */
      embedId: {
        default: null,
      },
      /** Human-readable label chosen by the LLM (e.g. "Ryanair 06:00 flight") */
      displayText: {
        default: "",
      },
      /** app_id from the embed — used for the gradient colour (e.g. "travel") */
      appId: {
        default: null,
      },
    };
  },

  // HTML parsing — lets TipTap reconstruct the node from saved HTML if needed
  parseHTML() {
    return [
      {
        tag: 'span[data-type="embed-inline"]',
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-type": "embed-inline",
        "data-embed-ref": HTMLAttributes.embedRef,
        "data-embed-id": HTMLAttributes.embedId,
        "data-display-text": HTMLAttributes.displayText,
        "data-app-id": HTMLAttributes.appId,
        class: "embed-inline-node",
        contenteditable: "false",
      }),
      HTMLAttributes.displayText || "",
    ];
  },

  // Vanilla DOM NodeView using Svelte 5 mount/unmount
  addNodeView() {
    return ({ node }) => {
      const dom = document.createElement("span");
      dom.setAttribute("data-type", "embed-inline");
      dom.setAttribute("contenteditable", "false");
      dom.classList.add("embed-inline-node");

      // Mount the Svelte 5 component into the span
      let svelteInstance: Record<string, unknown> | null = null;
      try {
        svelteInstance = mount(EmbedInlineLink, {
          target: dom,
          props: {
            embedRef: node.attrs.embedRef as string,
            embedId: node.attrs.embedId as string | null,
            displayText: node.attrs.displayText as string,
            appId: node.attrs.appId as string | null,
          },
        }) as Record<string, unknown>;
      } catch (err) {
        console.error(
          "[EmbedInlineNode] Failed to mount EmbedInlineLink:",
          err,
        );
        dom.textContent = node.attrs.displayText || "";
      }

      return {
        dom,
        update(updatedNode) {
          // Only handle updates to this node type
          if (updatedNode.type.name !== "embedInline") return false;
          // Attributes changed — re-mount with new props
          if (svelteInstance) {
            try {
              unmount(svelteInstance);
            } catch (_) {
              // Ignore unmount errors
            }
          }
          dom.innerHTML = "";
          try {
            svelteInstance = mount(EmbedInlineLink, {
              target: dom,
              props: {
                embedRef: updatedNode.attrs.embedRef as string,
                embedId: updatedNode.attrs.embedId as string | null,
                displayText: updatedNode.attrs.displayText as string,
                appId: updatedNode.attrs.appId as string | null,
              },
            }) as Record<string, unknown>;
          } catch (err) {
            console.error(
              "[EmbedInlineNode] Failed to re-mount EmbedInlineLink on update:",
              err,
            );
            dom.textContent = updatedNode.attrs.displayText || "";
          }
          return true;
        },
        destroy() {
          if (svelteInstance) {
            try {
              unmount(svelteInstance);
            } catch (_) {
              // Ignore unmount errors during destroy
            }
            svelteInstance = null;
          }
        },
      };
    };
  },
});
