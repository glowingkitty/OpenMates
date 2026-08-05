// frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/EmbedsMapViewRenderer.ts
// Renderer for the virtual `embeds-map-view` message node.
// This mounts a Svelte results-view component over existing embed refs and does not
// create, update, or enrich persisted embeds.
// Spec: docs/specs/embeds-map-view/spec.yml

import { mount, unmount } from "svelte";
import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import EmbedsMapView from "../../../embeds/EmbedsMapView.svelte";
import { hasStableResultViewIdentity } from "../streamingNodeIdentity";
import { incrementStreamingRenderMetric } from "../../../../message_parsing/streamingRenderMetrics";

type MountedMapView = ReturnType<typeof mount> & {
  updateDescriptor?: (attrs: EmbedNodeAttributes) => void;
};

const mountedComponents = new WeakMap<HTMLElement, {
  component: MountedMapView;
  attrs: EmbedNodeAttributes;
}>();

function copyAttrs(attrs: EmbedNodeAttributes): EmbedNodeAttributes {
  return {
    ...attrs,
    mapEmbedRefs: [...(attrs.mapEmbedRefs || [])],
    mapSourceRefs: [...(attrs.mapSourceRefs || [])],
    mapHighlightRefs: [...(attrs.mapHighlightRefs || [])],
  };
}

function refsToLine(key: string, refs: string[] | undefined): string {
  if (!refs || refs.length === 0) return "";
  return `${key}: ${refs.join(", ")}\n`;
}

export class EmbedsMapViewRenderer implements EmbedRenderer {
  type = "embeds-map-view";

  render(context: EmbedRenderContext): void {
    const { attrs, container, content } = context;
    this.destroy(context);

    container.setAttribute("data-testid", "embeds-map-view-renderer");
    container.setAttribute("data-embed-type", "embeds-map-view");

    incrementStreamingRenderMetric("nodeViewMounts");
    const component = mount(EmbedsMapView, {
      target: content,
      props: {
        id: attrs.id,
        title: attrs.title || "Results view",
        embedRefs: attrs.mapEmbedRefs || [],
        sourceRefs: attrs.mapSourceRefs || [],
        highlightRefs: attrs.mapHighlightRefs || [],
      },
    });
    mountedComponents.set(content, {
      component: component as MountedMapView,
      attrs: copyAttrs(attrs),
    });
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    return (
      "```embeds_results_view\n" +
      `title: ${attrs.title || "Results view"}\n` +
      refsToLine("embeds", attrs.mapEmbedRefs) +
      refsToLine("sources", attrs.mapSourceRefs) +
      refsToLine("highlight", attrs.mapHighlightRefs) +
      "```"
    );
  }

  update(context: EmbedRenderContext): boolean {
    const mounted = mountedComponents.get(context.content);
    if (!mounted || !hasStableResultViewIdentity(mounted.attrs, context.attrs)) {
      this.render(context);
      return true;
    }

    mounted.component.updateDescriptor?.(context.attrs);
    mounted.attrs = copyAttrs(context.attrs);
    return true;
  }

  destroy(context: EmbedRenderContext): void {
    const mounted = mountedComponents.get(context.content);
    if (!mounted) return;
    unmount(mounted.component);
    mountedComponents.delete(context.content);
  }
}
