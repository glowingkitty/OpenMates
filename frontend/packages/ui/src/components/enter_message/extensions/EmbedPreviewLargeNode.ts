// frontend/packages/ui/src/components/enter_message/extensions/EmbedPreviewLargeNode.ts
//
// TipTap block-level atom node for "large embed preview" cards.
//
// The LLM writes [!](embed:some-ref-k8D) (exclamation-mark display text) or
// [](embed:ref) (empty display text, auto-fallback) in its response.
// parse_message.ts detects these patterns, converts the markdown link
// into an `embedPreviewLarge` block node, and hoists it out of its parent
// paragraph so it renders as a block element.
//
// Consecutive `embedPreviewLarge` nodes (no other nodes between them) are
// rendered by EmbedPreviewLarge.svelte as a carousel (prev/next arrows, same
// design as DailyInspirationBanner).  A single isolated node is rendered as a
// full-width card without arrows.
//
// Architecture: block atom with Svelte NodeView (EmbedPreviewLarge.svelte).
// Tests: (none yet)

import { Node, mergeAttributes } from "@tiptap/core";
import { mount, unmount } from "svelte";
import EmbedPreviewLarge from "../../embeds/EmbedPreviewLarge.svelte";

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface EmbedPreviewLargeNodeOptions {}

export const EmbedPreviewLargeNode = Node.create<EmbedPreviewLargeNodeOptions>({
  name: "embedPreviewLarge",
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
      /**
       * Index in the consecutive run of large previews (0-based).
       * Set by parse_message._hoistBlockEmbedPreviews() so the Svelte component
       * knows its position within the carousel without scanning the DOM.
       */
      carouselIndex: {
        default: 0,
      },
      /**
       * Total number of consecutive large preview nodes in this run.
       * 1 = standalone card (no arrows), >1 = carousel.
       */
      carouselTotal: {
        default: 1,
      },
      /**
       * embedRef of the first card in this run. All cards in the run share the
       * same runRef so EmbedPreviewLarge can use it as the carousel store key
       * for synchronised navigation. Defaults to empty string (single card).
       */
      runRef: {
        default: '',
      },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'div[data-type="embed-preview-large"]',
        getAttrs(element: HTMLElement) {
          return {
            embedRef: element.getAttribute("data-embed-ref") ?? "",
            embedId: element.getAttribute("data-embed-id") || null,
            appId: element.getAttribute("data-app-id") || null,
            carouselIndex: parseInt(
              element.getAttribute("data-carousel-index") ?? "0",
              10,
            ),
            carouselTotal: parseInt(
              element.getAttribute("data-carousel-total") ?? "1",
              10,
            ),
            runRef: element.getAttribute("data-run-ref") ?? "",
          };
        },
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-type": "embed-preview-large",
        "data-embed-ref": HTMLAttributes.embedRef,
        "data-embed-id": HTMLAttributes.embedId,
        "data-app-id": HTMLAttributes.appId,
        "data-carousel-index": HTMLAttributes.carouselIndex,
        "data-carousel-total": HTMLAttributes.carouselTotal,
        "data-run-ref": HTMLAttributes.runRef,
        class: "embed-preview-large-node",
        contenteditable: "false",
      }),
      `[embed: ${HTMLAttributes.embedRef || ""}]`,
    ];
  },

  addNodeView() {
    return (nodeViewProps) => {
      let node = nodeViewProps.node;
      const dom = document.createElement("div");
      dom.setAttribute("data-type", "embed-preview-large");
      dom.setAttribute("contenteditable", "false");
      dom.classList.add("embed-preview-large-node");

      let svelteInstance: Record<string, unknown> | null = null;
      function mountComponent() {
        try {
          svelteInstance = mount(EmbedPreviewLarge, {
            target: dom,
            props: {
              embedRef: node.attrs.embedRef as string,
              embedId: node.attrs.embedId as string | null,
              appId: node.attrs.appId as string | null,
              carouselIndex: node.attrs.carouselIndex as number,
              carouselTotal: node.attrs.carouselTotal as number,
              runRef: node.attrs.runRef as string,
            },
          }) as Record<string, unknown>;
        } catch (err) {
          console.error(
            "[EmbedPreviewLargeNode] Failed to mount EmbedPreviewLarge:",
            err,
          );
          dom.textContent = `[embed: ${node.attrs.embedRef}]`;
        }
      }
      mountComponent();

      return {
        dom,
        update(updatedNode) {
          if (updatedNode.type.name !== "embedPreviewLarge") return false;

          const attrsMatch =
            updatedNode.attrs.embedRef === node.attrs.embedRef &&
            updatedNode.attrs.embedId === node.attrs.embedId &&
            updatedNode.attrs.appId === node.attrs.appId &&
            updatedNode.attrs.carouselIndex === node.attrs.carouselIndex &&
            updatedNode.attrs.carouselTotal === node.attrs.carouselTotal &&
            updatedNode.attrs.runRef === node.attrs.runRef;
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
          mountComponent();
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
