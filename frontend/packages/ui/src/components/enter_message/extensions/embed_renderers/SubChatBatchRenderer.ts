// frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/SubChatBatchRenderer.ts
//
// Renderer for the virtual `sub-chat-batch` message node.
// The node is created from a lightweight JSON marker in assistant content and
// mounts a Svelte carousel over existing child chat records. It does not create
// or mutate persisted embed rows.

import { mount, unmount } from "svelte";
import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import SubChatBatchPreview from "../../../sub_chats/SubChatBatchPreview.svelte";

const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

export class SubChatBatchRenderer implements EmbedRenderer {
  type = "sub-chat-batch";

  render(context: EmbedRenderContext): void {
    const { attrs, container, content } = context;
    this.destroy(context);

    container.setAttribute("data-testid", "sub-chat-batch-renderer");
    container.setAttribute("data-embed-type", "sub-chat-batch");

    const component = mount(SubChatBatchPreview, {
      target: content,
      props: {
        batchId: attrs.batchId || attrs.id,
        parentChatId: attrs.parentChatId || "",
        subChatIds: attrs.subChatIds || [],
        status: attrs.status,
      },
    });
    mountedComponents.set(content, component);
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    return (
      "```json\n" +
      JSON.stringify({
        type: "sub_chat_batch",
        batch_id: attrs.batchId || attrs.id,
        chat_id: attrs.parentChatId,
        status: attrs.status,
        sub_chat_ids: attrs.subChatIds || [],
      }) +
      "\n```"
    );
  }

  update(context: EmbedRenderContext): boolean {
    this.render(context);
    return true;
  }

  destroy(context: EmbedRenderContext): void {
    const component = mountedComponents.get(context.content);
    if (!component) return;
    unmount(component);
    mountedComponents.delete(context.content);
  }
}
