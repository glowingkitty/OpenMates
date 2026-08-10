// frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/__tests__/EmbedsMapViewRenderer.test.ts
// Renderer contract for the virtual in-chat embeds results view.
// The renderer must mount a local Svelte component and must not trigger provider
// or app-skill work while rendering message refs.
// Spec: docs/specs/embeds-map-view/spec.yml

import { beforeEach, describe, expect, it, vi } from "vitest";
import EmbedsMapView from "../../../../embeds/EmbedsMapView.svelte";
import { EmbedsMapViewRenderer } from "../EmbedsMapViewRenderer";

const svelteMountMocks = vi.hoisted(() => ({
  mount: vi.fn(() => ({ destroy: vi.fn() })),
  unmount: vi.fn(),
}));

vi.mock("svelte", async (importOriginal) => {
  const actual = await importOriginal<typeof import("svelte")>();
  return {
    ...actual,
    mount: svelteMountMocks.mount,
    unmount: svelteMountMocks.unmount,
  };
});

describe("EmbedsMapViewRenderer", () => {
  beforeEach(() => {
    svelteMountMocks.mount.mockClear();
    svelteMountMocks.unmount.mockClear();
  });

  it("mounts the map view with refs, sources, and highlights", () => {
    const renderer = new EmbedsMapViewRenderer();
    const container = document.createElement("div");
    const content = document.createElement("div");
    container.appendChild(content);

    renderer.render({
      attrs: {
        id: "map-view-1",
        type: "embeds-map-view",
        status: "finished",
        contentRef: "map-view:map-view-1",
        title: "Berlin AI events",
        mapEmbedRefs: ["event-one-111111", "event-two-222222"],
        mapSourceRefs: ["events-search-abcdef"],
        mapHighlightRefs: ["event-two-222222"],
      },
      container,
      content,
    });

    expect(svelteMountMocks.mount).toHaveBeenCalledWith(
      EmbedsMapView,
      expect.objectContaining({
        target: content,
        props: expect.objectContaining({
          id: "map-view-1",
          title: "Berlin AI events",
          embedRefs: ["event-one-111111", "event-two-222222"],
          sourceRefs: ["events-search-abcdef"],
          highlightRefs: ["event-two-222222"],
        }),
      }),
    );
    expect(container.dataset.testid).toBe("embeds-map-view-renderer");
  });

  it("serializes back to compact fenced syntax", () => {
    const renderer = new EmbedsMapViewRenderer();

    expect(
      renderer.toMarkdown({
        id: "map-view-1",
        type: "embeds-map-view",
        status: "finished",
        contentRef: "map-view:map-view-1",
        title: "Munich to Zurich options",
        mapSourceRefs: ["travel-search-connections-12ab34"],
        mapHighlightRefs: ["nightjet-7abc12"],
      }),
    ).toBe(
      "```embeds_results_view\n" +
        "title: Munich to Zurich options\n" +
        "sources: travel-search-connections-12ab34\n" +
        "highlight: nightjet-7abc12\n" +
        "```",
    );
  });
});
