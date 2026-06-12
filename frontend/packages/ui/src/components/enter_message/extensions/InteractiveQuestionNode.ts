/**
 * frontend/packages/ui/src/components/enter_message/extensions/InteractiveQuestionNode.ts
 *
 * TipTap block-level atom node for rendering custom "interactive_question" components.
 * Intercepts ```interactive_question blocks during message rendering, parses the JSON payload,
 * and mounts the InteractiveQuestionContainer.svelte Svelte component.
 *
 * Architecture: Block atom with Svelte 5 NodeView (InteractiveQuestionContainer.svelte).
 */

import { Node, mergeAttributes } from "@tiptap/core";
import { mount, unmount } from "svelte";
import { get } from "svelte/store";
import InteractiveQuestionContainer from "../../interactive_questions/InteractiveQuestionContainer.svelte";
import type { InteractiveQuestionPayload } from "../../interactive_questions/types";
import { isInteractiveQuestionPayload } from "../../interactive_questions/utils/questionState";
import { text } from "../../../i18n/translations";

// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface InteractiveQuestionNodeOptions {}

export const InteractiveQuestionNode = Node.create<InteractiveQuestionNodeOptions>({
  name: "interactiveQuestion",
  group: "block",
  atom: true,
  selectable: true,
  draggable: false,

  renderText({ node }) {
    return `[interactive-question: ${node.attrs.id}]`;
  },

  addAttributes() {
    return {
      id: {
        default: "",
      },
      json: {
        default: "",
      },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'div[data-type="interactive-question"]',
        getAttrs(element: HTMLElement) {
          return {
            id: element.getAttribute("data-id") ?? "",
            json: element.getAttribute("data-json") ?? "",
          };
        },
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-type": "interactive-question",
        "data-id": HTMLAttributes.id,
        "data-json": HTMLAttributes.json,
        class: "interactive-question-node",
        contenteditable: "false",
      }),
      `[interactive-question: ${HTMLAttributes.id || ""}]`,
    ];
  },

  addNodeView() {
    return (nodeViewProps) => {
      let node = nodeViewProps.node;
      const dom = document.createElement("div");
      dom.setAttribute("data-type", "interactive-question");
      dom.setAttribute("contenteditable", "false");
      dom.classList.add("interactive-question-node");

      // Resolve the parent chat context from global or surrounding DOM references if available
      const chatIdAttr = nodeViewProps.editor.options.element.closest('[data-chat-id]')?.getAttribute('data-chat-id') || "";

      let svelteInstance: Record<string, unknown> | null = null;
      let parsedPayload: InteractiveQuestionPayload | null = null;

      function fallbackText() {
        return get(text)("chat.interactive_question_failed");
      }

      try {
        const parsed = JSON.parse(node.attrs.json) as unknown;
        parsedPayload = isInteractiveQuestionPayload(parsed) ? parsed : null;
      } catch (_err) {
        console.error("[InteractiveQuestionNode] Failed to parse payload JSON:", _err);
      }

      function mountComponent() {
        if (!parsedPayload) {
          dom.textContent = fallbackText();
          return;
        }

        try {
          svelteInstance = mount(InteractiveQuestionContainer, {
            target: dom,
            props: {
              payload: parsedPayload,
              chatId: chatIdAttr,
              // chatHistory will be dynamically scanned asynchronously in the container via IndexedDB/store
            },
          }) as Record<string, unknown>;
        } catch (_err) {
          console.error(
            "[InteractiveQuestionNode] Failed to mount InteractiveQuestionContainer:",
            _err,
          );
          dom.textContent = fallbackText();
        }
      }

      mountComponent();

      return {
        dom,
        update(updatedNode) {
          if (updatedNode.type.name !== "interactiveQuestion") return false;

          const attrsMatch =
            updatedNode.attrs.id === node.attrs.id &&
            updatedNode.attrs.json === node.attrs.json;
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
            const parsed = JSON.parse(node.attrs.json) as unknown;
            parsedPayload = isInteractiveQuestionPayload(parsed) ? parsed : null;
          } catch (_err) {
            parsedPayload = null;
          }
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
