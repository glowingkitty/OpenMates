// @vitest-environment jsdom
// frontend/packages/ui/src/components/embeds/__tests__/EmbedsMapView.test.ts
// Component-level tests for the virtual embeds map/list view.
// These use mocked local embed data only, proving the component derives list
// filters and bounded source children without provider/app-skill calls.
// Spec: docs/specs/embeds-map-view/spec.yml

import { mount, tick, unmount } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EmbedsMapView from "../EmbedsMapView.svelte";

const embedResolverMocks = vi.hoisted(() => ({
  resolveEmbed: vi.fn(),
  decodeToonContent: vi.fn(),
}));

const embedStoreMocks = vi.hoisted(() => ({
  resolveByRefDeep: vi.fn(),
  subscribe: vi.fn((run: (value: number) => void) => {
    run(0);
    return () => undefined;
  }),
}));

const fullscreenMocks = vi.hoisted(() => ({
  dispatchEmbedFullscreen: vi.fn(),
}));

vi.mock("../../../services/embedResolver", () => embedResolverMocks);
vi.mock("../../../services/embedStore", () => ({
  embedStore: {
    resolveByRefDeep: embedStoreMocks.resolveByRefDeep,
  },
  embedRefIndexVersion: {
    subscribe: embedStoreMocks.subscribe,
  },
}));
vi.mock("../../../services/embedFullscreenController", () => fullscreenMocks);

async function flush(): Promise<void> {
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await tick();
}

describe("EmbedsMapView", () => {
  beforeEach(() => {
    embedResolverMocks.resolveEmbed.mockReset();
    embedResolverMocks.decodeToonContent.mockReset();
    embedStoreMocks.resolveByRefDeep.mockReset();
    fullscreenMocks.dispatchEmbedFullscreen.mockReset();

    embedStoreMocks.resolveByRefDeep.mockImplementation(async (ref: string) => {
      const map: Record<string, string> = {
        "events-search-abcdef": "source-embed-id",
        "event-one-111111": "event-one-id",
        "place-two-222222": "place-two-id",
      };
      return map[ref] || ref;
    });

    embedResolverMocks.resolveEmbed.mockImplementation(async (embedId: string) => {
      if (embedId === "source-embed-id") {
        return {
          embed_id: embedId,
          type: "app_skill_use",
          status: "finished",
          content: "source-content",
          embed_ids: ["event-one-111111", "place-two-222222"],
          createdAt: 1,
          updatedAt: 1,
        };
      }
      if (embedId === "event-one-id") {
        return {
          embed_id: embedId,
          type: "events-event",
          status: "finished",
          content: "event-content",
          createdAt: 1,
          updatedAt: 1,
        };
      }
      if (embedId === "place-two-id") {
        return {
          embed_id: embedId,
          type: "maps-place",
          status: "finished",
          content: "place-content",
          createdAt: 1,
          updatedAt: 1,
        };
      }
      return null;
    });

    embedResolverMocks.decodeToonContent.mockImplementation(async (content: string) => {
      if (content === "source-content") return { app_id: "events", skill_id: "search" };
      if (content === "event-content") {
        return {
          app_id: "events",
          skill_id: "event",
          title: "AI Founders Meetup",
          date_start: "2026-08-01T18:00:00Z",
          venue: { address: "Berlin" },
        };
      }
      if (content === "place-content") {
        return {
          app_id: "maps",
          skill_id: "place",
          displayName: "Factory Berlin",
          formattedAddress: "Lohmuehlenstrasse 65, Berlin",
        };
      }
      return null;
    });
  });

  it("loads source children, sorts highlights first, and derives filters", async () => {
    const target = document.createElement("div");
    document.body.appendChild(target);

    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-1",
        title: "Berlin AI events",
        embedRefs: [],
        sourceRefs: ["events-search-abcdef"],
        highlightRefs: ["place-two-222222"],
      },
    });

    await flush();

    const cards = Array.from(target.querySelectorAll('[data-testid="embeds-map-view-card"]'));
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain("Factory Berlin");
    expect(cards[0].classList.contains("highlighted")).toBe(true);
    expect(target.querySelector('[data-testid="embeds-map-view-filters"]')?.textContent).toContain("event");
    expect(target.querySelector('[data-testid="embeds-map-view-filters"]')?.textContent).toContain("place");
    expect(embedResolverMocks.resolveEmbed).toHaveBeenCalledTimes(3);
    expect(fullscreenMocks.dispatchEmbedFullscreen).not.toHaveBeenCalled();

    unmount(component);
    target.remove();
  });
});
