// MathPlotRenderer.ts
//
// Direct-type renderer for "math-plot" embed nodes in the TipTap editor.
//
// Math plot embeds are auto-detected by stream_consumer.py from ```plot ... ``` fenced
// code blocks in LLM output. The backend replaces them with a JSON embed reference:
//   {"type": "math-plot", "embed_id": "<uuid>", "code": "<plot spec>"}
//
// This renderer mounts MathPlotEmbedPreview.svelte into the node-view wrapper and
// dispatches a fullscreen event so ActiveChat can open MathPlotEmbedFullscreen.

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import { mount, unmount } from "svelte";
import MathPlotEmbedPreview from "../../../embeds/math/MathPlotEmbedPreview.svelte";

// Track mounted Svelte components for cleanup so we can unmount before re-rendering
const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

export class MathPlotRenderer implements EmbedRenderer {
  type = "math-plot";

  render(context: EmbedRenderContext): void {
    const { content, attrs } = context;

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
      // Extract plot spec from attrs — the backend stores the plot code in attrs.code
      // (same field used for code-code embeds). Falls back to attrs.plot_spec if set.
      const extAttrs = attrs as EmbedNodeAttributes & {
        code?: string;
        plot_spec?: string;
        title?: string;
      };
      const plotSpec = extAttrs.code || extAttrs.plot_spec || "";
      const title = extAttrs.title || "Function Plot";
      const status =
        (attrs.status as "processing" | "finished" | "error") || "finished";

      // Derive the real embed_id from contentRef (same pattern as MapLocationRenderer)
      const embedId = attrs.contentRef?.startsWith("embed:")
        ? attrs.contentRef.replace("embed:", "")
        : (attrs.id ?? "");

      // Dispatch fullscreen event so ActiveChat opens MathPlotEmbedFullscreen
      const handleFullscreen = () => {
        document.dispatchEvent(
          new CustomEvent("embedfullscreen", {
            bubbles: true,
            detail: {
              embedType: "math-plot",
              embedId,
              attrs: {
                code: plotSpec,
                plot_spec: plotSpec,
                title,
                status,
              },
              embedData: {
                type: "math-plot",
                status,
              },
              decodedContent: {
                plot_spec: plotSpec,
                title,
                status,
              },
            },
          }),
        );
      };

      const component = mount(MathPlotEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          plotSpec,
          status,
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);

      console.debug("[MathPlotRenderer] Mounted MathPlotEmbedPreview:", {
        embedId,
        plotSpecLength: plotSpec.length,
        title,
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
    // Convert back to a plot fenced code block for copy/export
    const extAttrs = attrs as EmbedNodeAttributes & {
      code?: string;
      plot_spec?: string;
    };
    const plotSpec = extAttrs.code || extAttrs.plot_spec || "";
    return `\`\`\`plot\n${plotSpec}\n\`\`\`\n\n`;
  }

  update(context: EmbedRenderContext): boolean {
    // Re-render when attrs change (e.g. live streaming updates)
    this.render(context);
    return true;
  }
}
