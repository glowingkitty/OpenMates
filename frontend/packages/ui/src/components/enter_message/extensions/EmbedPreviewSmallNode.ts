// frontend/packages/ui/src/components/enter_message/extensions/EmbedPreviewSmallNode.ts
//
// TipTap block-level atom node for inline "small embed preview" cards.
//
// The LLM writes [](embed:some-ref-k8D) (empty display text) in its response.
// parse_message.ts detects this pattern, converts the inline markdown link into
// an `embedPreviewSmall` block node, and hoists it out of its parent paragraph
// so it renders as a block element (not inside a run of text).
//
// Visual design:
//   A compact (~300×120px) clickable card that shows:
//   - Gradient app icon badge (left)
//   - Embed reference name / resolved title (centre)
//   - Processing indicator or "finished" status (right)
//   Clicking opens the embed fullscreen (same `embedfullscreen` event as
//   EmbedInlineLink).
//
// Architecture: analogous to SourceQuoteNode (block atom with Svelte NodeView).
// Tests: (none yet)

import { Node, mergeAttributes } from "@tiptap/core";
import { mount, unmount } from "svelte";
import EmbedPreviewSmall from "../../embeds/EmbedPreviewSmall.svelte";

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface EmbedPreviewSmallNodeOptions {}

export const EmbedPreviewSmallNode = Node.create<EmbedPreviewSmallNodeOptions>({
  name: "embedPreviewSmall",
  group: "block",
  atom: true,
  selectable: true,
  draggable: false,

  renderText({ node }) {
    return `[embed: ${node.attrs.embedRef}]`;
  },

  addAttributes() {
    return {
      /** Short slug from the LLM (e.g. "ryanair-0600-k8D") */
      embedRef: {
        default: "",
      },
      /** Pre-resolved UUID — may be null when the node is first created */
      embedId: {
        default: null,
      },
      /** app_id hint from parse-time — may be null */
      appId: {
        default: null,
      },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'div[data-type="embed-preview-small"]',
        getAttrs(element: HTMLElement) {
          return {
            embedRef: element.getAttribute("data-embed-ref") ?? "",
            embedId: element.getAttribute("data-embed-id") || null,
            appId: element.getAttribute("data-app-id") || null,
          };
        },
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-type": "embed-preview-small",
        "data-embed-ref": HTMLAttributes.embedRef,
        "data-embed-id": HTMLAttributes.embedId,
        "data-app-id": HTMLAttributes.appId,
        class: "embed-preview-small-node",
        contenteditable: "false",
      }),
      `[embed: ${HTMLAttributes.embedRef || ""}]`,
    ];
  },

  addNodeView() {
    return (nodeViewProps) => {
      let node = nodeViewProps.node;
      const dom = document.createElement("div");
      dom.setAttribute("data-type", "embed-preview-small");
      dom.setAttribute("contenteditable", "false");
      dom.classList.add("embed-preview-small-node");

      let svelteInstance: Record<string, unknown> | null = null;
      try {
        svelteInstance = mount(EmbedPreviewSmall, {
          target: dom,
          props: {
            embedRef: node.attrs.embedRef as string,
            embedId: node.attrs.embedId as string | null,
            appId: node.attrs.appId as string | null,
          },
        }) as Record<string, unknown>;
      } catch (err) {
        console.error(
          "[EmbedPreviewSmallNode] Failed to mount EmbedPreviewSmall:",
          err,
        );
        dom.textContent = `[embed: ${node.attrs.embedRef}]`;
      }

      return {
        dom,
        update(updatedNode) {
          if (updatedNode.type.name !== "embedPreviewSmall") return false;

          const attrsMatch =
            updatedNode.attrs.embedRef === node.attrs.embedRef &&
            updatedNode.attrs.embedId === node.attrs.embedId &&
            updatedNode.attrs.appId === node.attrs.appId;
          if (attrsMatch) {
            node = updatedNode;
            return true;
          }

          node = updatedNode;
          if (svelteInstance) {
            try {
              unmount(svelteInstance);
            } catch {
              /* ignore */
            }
          }
          dom.innerHTML = "";
          try {
            svelteInstance = mount(EmbedPreviewSmall, {
              target: dom,
              props: {
                embedRef: node.attrs.embedRef as string,
                embedId: node.attrs.embedId as string | null,
                appId: node.attrs.appId as string | null,
              },
            }) as Record<string, unknown>;
          } catch (err) {
            console.error(
              "[EmbedPreviewSmallNode] Failed to re-mount EmbedPreviewSmall:",
              err,
            );
            dom.textContent = `[embed: ${node.attrs.embedRef}]`;
          }
          return true;
        },
        destroy() {
          if (svelteInstance) {
            try {
              unmount(svelteInstance);
            } catch {
              /* ignore */
            }
            svelteInstance = null;
          }
        },
      };
    };
  },
});
