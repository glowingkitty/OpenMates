// MapLocationRenderer.ts
//
// Renderer for "maps" embed nodes in the TipTap editor.
//
// When the user selects a location via MapsView the embed node is inserted with:
//   type: "maps"
//   contentRef: "embed:{uuid}"   ← key into EmbedStore
//   preciseLat / preciseLon      ← pin coordinates for preview
//   zoom                         ← initial Leaflet zoom level
//   name                         ← short display label
//
// This renderer mounts MapsLocationEmbedPreview.svelte directly into the node-view
// wrapper (the "maps" type is listed in svelteComponentEmbedTypes so TipTap mounts
// the Svelte component without an intermediate container div).
//
// The Leaflet map inside MapsLocationEmbedPreview is non-interactive by default so
// the user can still navigate the editor normally while the pin shows the location.

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import { mount, unmount } from "svelte";
import MapsLocationEmbedPreview from "../../../embeds/maps/MapsLocationEmbedPreview.svelte";

// Track mounted Svelte components for cleanup so we can unmount before re-rendering
const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

export class MapLocationRenderer implements EmbedRenderer {
  type = "maps";

  render(context: EmbedRenderContext): void {
    const { content, attrs } = context;

    // Unmount any previously mounted Svelte component on this DOM node
    const existing = mountedComponents.get(content);
    if (existing) {
      try {
        unmount(existing);
      } catch (e) {
        console.warn(
          "[MapLocationRenderer] Error unmounting existing preview:",
          e,
        );
      }
    }

    content.innerHTML = "";

    try {
      // Derive display coordinates: use preciseLat/preciseLon for the pin.
      // These are registered as TipTap attributes so they survive DOM round-trips.
      // Cast to access the extended attrs that are not in the base EmbedNodeAttributes type.
      const extAttrs = attrs as EmbedNodeAttributes & {
        preciseLat?: number | null;
        preciseLon?: number | null;
        name?: string;
        address?: string;
        locationType?: string | null;
      };
      const lat = extAttrs.preciseLat ?? null;
      const lon = extAttrs.preciseLon ?? null;
      const name = extAttrs.name ?? "";
      const address = extAttrs.address ?? "";
      const locationType = extAttrs.locationType ?? "area";
      const status =
        (attrs.status as "processing" | "finished" | "error") || "finished";

      // Dispatch fullscreen event on document (same pattern as AppSkillUseRenderer).
      // ActiveChat listens on document for 'embedfullscreen' events.
      const handleFullscreen = () => {
        document.dispatchEvent(
          new CustomEvent("embedfullscreen", {
            bubbles: true,
            detail: {
              embedType: "maps",
              // embedId: strip "embed:" prefix so ActiveChat can look up EmbedStore
              embedId: attrs.contentRef?.startsWith("embed:")
                ? attrs.contentRef.replace("embed:", "")
                : undefined,
              attrs: {
                lat,
                lon,
                name,
                address,
                locationType,
                status,
                preciseLat: lat,
                preciseLon: lon,
              },
              embedData: {
                type: "maps",
                status,
              },
              // decodedContent is the fallback when EmbedStore lookup fails or embedId is missing.
              // Include all fields so the fullscreen can render correctly from attrs alone.
              decodedContent: {
                lat,
                lon,
                name,
                address,
                location_type: locationType,
                status,
              },
            },
          }),
        );
      };

      const component = mount(MapsLocationEmbedPreview, {
        target: content,
        props: {
          id: attrs.id ?? "",
          name,
          address,
          locationType,
          status,
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);

      console.debug("[MapLocationRenderer] Mounted MapsLocationEmbedPreview:", {
        id: attrs.id,
        lat,
        lon,
        name,
      });
    } catch (error) {
      console.error(
        "[MapLocationRenderer] Error mounting MapsLocationEmbedPreview:",
        error,
      );
      content.innerHTML = `<div style="padding:8px;font-size:12px;color:var(--color-grey-50)">Location unavailable</div>`;
    }
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    // Maps embeds are deleted on Backspace (handled in Embed.ts), not converted to markdown.
    // This method is a safe fallback only.
    const extAttrs = attrs as EmbedNodeAttributes & { name?: string };
    return `[Location: ${extAttrs.name ?? ""}]`;
  }

  update(context: EmbedRenderContext): boolean {
    // Re-render when attrs change (e.g. during hot-reload in development)
    this.render(context);
    return true;
  }
}
