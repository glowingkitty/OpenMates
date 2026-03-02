// MathPlotRenderer.ts
//
// Direct-type renderer for "math-plot" embed nodes in the TipTap editor.
//
// Math plot embeds are auto-detected by stream_consumer.py from ```plot ... ``` fenced
// code blocks in LLM output. The backend replaces them with a JSON embed reference:
//   {"type": "math-plot", "embed_id": "<uuid>"}
//
// The plot spec (function definitions) is stored as encrypted TOON content in IDB —
// it is NOT stored in TipTap node attrs. The spec reaches the preview card via
// UnifiedEmbedPreview.refetchFromStore() → onEmbedDataUpdated → handleEmbedDataUpdated.
//
// This renderer mounts MathPlotEmbedPreview.svelte into the node-view wrapper and
// dispatches a fullscreen event so ActiveChat can open MathPlotEmbedFullscreen.

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import { mount, unmount } from "svelte";
import MathPlotEmbedPreview from "../../../embeds/math/MathPlotEmbedPreview.svelte";
import { resolveEmbed } from "../../../../services/embedResolver";
import { chatSyncService } from "../../../../services/chatSyncService";
import { unmarkEmbedAsProcessed } from "../../../../services/chatSyncServiceHandlersAI";
import { embedStore } from "../../../../services/embedStore";

// Track mounted Svelte components for cleanup so we can unmount before re-rendering
const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

export class MathPlotRenderer implements EmbedRenderer {
  type = "math-plot";

  async render(context: EmbedRenderContext): Promise<void> {
    const { content, attrs } = context;

    const status =
      (attrs.status as "processing" | "finished" | "error") || "finished";

    // Derive the real embed_id from contentRef (same pattern as MapLocationRenderer)
    const embedId = attrs.contentRef?.startsWith("embed:")
      ? attrs.contentRef.replace("embed:", "")
      : (attrs.id ?? "");

    // DECRYPTION FAILURE RECOVERY:
    // If the embed is in IDB but failed to decrypt (e.g. the embed key was wrapped with
    // a random throwaway chat key due to the getOrGenerateChatKey race condition on a
    // brand-new chat when multiple embeds finalize concurrently), evict the corrupted
    // IDB entry and re-request fresh plaintext from the server.
    //
    // This is the same pattern used by AppSkillUseRenderer.ts:75–133.
    //
    // math-plot plot specs travel exclusively in the encrypted IDB content (not in TipTap
    // attrs), so a corrupted IDB entry permanently breaks the preview card (status="error",
    // blank formula area) without this recovery path.
    if (embedId) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const existingEmbed = (await resolveEmbed(embedId)) as any;
      if (existingEmbed?._decryptionFailed) {
        console.warn(
          "[MathPlotRenderer] Embed decryption failed — evicting and re-requesting from server:",
          embedId,
        );
        try {
          await embedStore.deleteEmbed(embedId);
        } catch (deleteErr) {
          console.warn(
            "[MathPlotRenderer] Could not evict decryption-failed embed:",
            deleteErr,
          );
        }

        // One-shot listener: re-render as soon as fresh embed data arrives.
        const decryptRetryHandler = (event: Event) => {
          const customEvent = event as CustomEvent<{ embed_id: string }>;
          if (customEvent.detail?.embed_id !== embedId) return;
          chatSyncService.removeEventListener(
            "embedUpdated",
            decryptRetryHandler,
          );
          this.render(context).catch((err) => {
            console.error(
              "[MathPlotRenderer] Error in decryption-retry re-render:",
              err,
            );
          });
        };
        chatSyncService.addEventListener("embedUpdated", decryptRetryHandler);

        // Allow the incoming send_embed_data to be processed — without this the
        // isEmbedAlreadyProcessed guard in chatSyncServiceHandlersAI silently drops
        // the re-delivered event, preventing re-encryption with the correct key.
        unmarkEmbedAsProcessed(embedId);

        // Ask the server to resend the embed's plaintext TOON content (with embed_keys
        // so the client can re-encrypt it correctly now that the chat key is loaded).
        try {
          const { webSocketService } =
            await import("../../../../services/websocketService");
          await webSocketService.sendMessage("request_embed", {
            embed_id: embedId,
          });
        } catch (reqErr) {
          console.warn(
            "[MathPlotRenderer] Could not request embed after decryption failure:",
            reqErr,
          );
        }

        // Leave the node empty while waiting for the server response.
        content.innerHTML = "";
        return;
      }
    }

    // Unmount any previously mounted Svelte component on this DOM node
    const existing = mountedComponents.get(content);
    if (existing) {
      try {
        unmount(existing);
      } catch (e) {
        console.warn(
          "[MathPlotRenderer] Error unmounting existing preview:",
          e,
        );
      }
    }

    content.innerHTML = "";

    try {
      // Dispatch fullscreen event so ActiveChat opens MathPlotEmbedFullscreen.
      // decodedContent is intentionally empty here — the actual plot_spec is loaded
      // by UnifiedEmbedPreview.refetchFromStore() after mount, which calls
      // onEmbedDataUpdated → handleEmbedDataUpdated in MathPlotEmbedPreview.
      const handleFullscreen = () => {
        document.dispatchEvent(
          new CustomEvent("embedfullscreen", {
            bubbles: true,
            detail: {
              embedType: "math-plot",
              embedId,
              attrs: { status },
              embedData: { type: "math-plot", status },
              decodedContent: { status },
            },
          }),
        );
      };

      const component = mount(MathPlotEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          plotSpec: "", // UnifiedEmbedPreview.refetchFromStore() fills this via onEmbedDataUpdated
          status,
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);

      console.debug("[MathPlotRenderer] Mounted MathPlotEmbedPreview:", {
        embedId,
        status,
      });
    } catch (error) {
      console.error(
        "[MathPlotRenderer] Error mounting MathPlotEmbedPreview:",
        error,
      );
      content.innerHTML = `<div style="padding:8px;font-size:12px;color:var(--color-grey-50)">Plot unavailable</div>`;
    }
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    // Math-plot content is stored in encrypted IDB — the plot spec is not available
    // in TipTap attrs. Emit a placeholder so the message round-trips as valid markdown.
    void attrs;
    return `\`\`\`plot\n# Plot content encrypted — open fullscreen to view\n\`\`\`\n\n`;
  }

  update(context: EmbedRenderContext): boolean {
    // Re-render when attrs change (e.g. live streaming status updates).
    // render() is async; fire-and-forget is safe here — errors are logged internally.
    this.render(context).catch((err) => {
      console.error("[MathPlotRenderer] Error in update re-render:", err);
    });
    return true;
  }
}
