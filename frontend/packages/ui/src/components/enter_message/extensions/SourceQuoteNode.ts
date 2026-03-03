// frontend/packages/ui/src/components/enter_message/extensions/SourceQuoteNode.ts
//
// TipTap block-level atom node for verified source quotes produced by the LLM.
//
// The LLM writes:
//   > [quoted text](embed:some-ref-k8D)
//
// After post-streaming verification (stream_consumer.py), this syntax survives
// in the message only if the quote is verified against the embed source content.
//
// parse_message.ts converts matching blockquote nodes (blockquote containing a
// single paragraph with a single text node that has an embed: link mark wrapping
// the entire text) into `sourceQuote` atom nodes with the attributes below.
//
// The node is read-only and atom (treated as a single unit). On click the
// SourceQuoteBlock Svelte component dispatches a document-level "embedfullscreen"
// CustomEvent with `highlightQuoteText` in the detail, so the fullscreen panel
// can scroll to and highlight the quoted text in the source content.
//
// Architecture context: See docs/architecture/source-quotes.md
// Tests: (none yet)

import { Node, mergeAttributes } from "@tiptap/core";
import { mount, unmount } from "svelte";
import SourceQuoteBlock from "../../embeds/SourceQuoteBlock.svelte";

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface SourceQuoteNodeOptions {}

export const SourceQuoteNode = Node.create<SourceQuoteNodeOptions>({
  name: "sourceQuote",
  group: "block",
  atom: true,
  selectable: true,
  draggable: false,

  // renderText so the node contributes to plain-text extraction (e.g. copy)
  renderText({ node }) {
    return `"${node.attrs.quoteText}" — ${node.attrs.embedRef}`;
  },

  addAttributes() {
    return {
      /** The exact quoted text from the source */
      quoteText: {
        default: "",
      },
      /** Short slug from the embed_ref (e.g. "wikipedia.org-k8D") */
      embedRef: {
        default: "",
      },
      /** app_id from the embed — used for accent colour */
      appId: {
        default: null,
      },
    };
  },

  // HTML parsing — lets TipTap reconstruct the node from saved HTML if needed
  parseHTML() {
    return [
      {
        tag: 'div[data-type="source-quote"]',
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-type": "source-quote",
        "data-quote-text": HTMLAttributes.quoteText,
        "data-embed-ref": HTMLAttributes.embedRef,
        "data-app-id": HTMLAttributes.appId,
        class: "source-quote-node",
        contenteditable: "false",
      }),
      `"${HTMLAttributes.quoteText || ""}" — ${HTMLAttributes.embedRef || ""}`,
    ];
  },

  // Vanilla DOM NodeView using Svelte 5 mount/unmount
  addNodeView() {
    return ({ node }) => {
      const dom = document.createElement("div");
      dom.setAttribute("data-type", "source-quote");
      dom.setAttribute("contenteditable", "false");
      dom.classList.add("source-quote-node");

      // Mount the Svelte 5 component into the div
      let svelteInstance: Record<string, unknown> | null = null;
      try {
        svelteInstance = mount(SourceQuoteBlock, {
          target: dom,
          props: {
            quoteText: node.attrs.quoteText as string,
            embedRef: node.attrs.embedRef as string,
            appId: node.attrs.appId as string | null,
          },
        }) as Record<string, unknown>;
      } catch (err) {
        console.error(
          "[SourceQuoteNode] Failed to mount SourceQuoteBlock:",
          err,
        );
        dom.textContent = `"${node.attrs.quoteText}" — ${node.attrs.embedRef}`;
      }

      return {
        dom,
        update(updatedNode) {
          // Only handle updates to this node type
          if (updatedNode.type.name !== "sourceQuote") return false;
          // Attributes changed — re-mount with new props
          if (svelteInstance) {
            try {
              unmount(svelteInstance);
            } catch {
              // Ignore unmount errors
            }
          }
          dom.innerHTML = "";
          try {
            svelteInstance = mount(SourceQuoteBlock, {
              target: dom,
              props: {
                quoteText: updatedNode.attrs.quoteText as string,
                embedRef: updatedNode.attrs.embedRef as string,
                appId: updatedNode.attrs.appId as string | null,
              },
            }) as Record<string, unknown>;
          } catch (err) {
            console.error(
              "[SourceQuoteNode] Failed to re-mount SourceQuoteBlock on update:",
              err,
            );
            dom.textContent = `"${updatedNode.attrs.quoteText}" — ${updatedNode.attrs.embedRef}`;
          }
          return true;
        },
        destroy() {
          if (svelteInstance) {
            try {
              unmount(svelteInstance);
            } catch {
              // Ignore unmount errors during destroy
            }
            svelteInstance = null;
          }
        },
      };
    };
  },
});
