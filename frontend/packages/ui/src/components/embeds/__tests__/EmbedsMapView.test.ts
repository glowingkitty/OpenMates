// @vitest-environment jsdom
// frontend/packages/ui/src/components/embeds/__tests__/EmbedsMapView.test.ts
// Component-level tests for the virtual embeds results view.
// These use mocked local embed data only, proving the component derives list
// filters and bounded source children without provider/app-skill calls.
// Spec: docs/specs/embeds-map-view/spec.yml

import { mount, tick, unmount } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EmbedsMapView from "../EmbedsMapView.svelte";
import UnifiedEmbedPreview from "../UnifiedEmbedPreview.svelte";

const embedResolverMocks = vi.hoisted(() => ({
  resolveEmbed: vi.fn(),
  decodeToonContent: vi.fn(),
}));

const embedStoreMocks = vi.hoisted(() => ({
  resolveByRefDeep: vi.fn(),
  subscribeRefIndex: vi.fn((run: (value: number) => void) => {
    (globalThis as typeof globalThis & { __emitMapViewRefIndex?: (value: number) => void }).__emitMapViewRefIndex = run;
    run(0);
    return () => undefined;
  }),
  subscribeAvailability: vi.fn((run: (value: number) => void) => {
    (globalThis as typeof globalThis & { __emitMapViewEmbedAvailability?: (value: number) => void }).__emitMapViewEmbedAvailability = run;
    run(0);
    return () => undefined;
  }),
}));

const fullscreenMocks = vi.hoisted(() => ({
  dispatchEmbedFullscreen: vi.fn(),
}));

const previewRegistryMocks = vi.hoisted(() => ({
  resolve: vi.fn(),
}));

vi.mock("../../../services/embedResolver", () => embedResolverMocks);
vi.mock("../../../services/embedStore", () => ({
  embedStore: {
    resolveByRefDeep: embedStoreMocks.resolveByRefDeep,
  },
  embedRefIndexVersion: {
    subscribe: embedStoreMocks.subscribeRefIndex,
  },
  embedAvailabilityVersion: {
    subscribe: embedStoreMocks.subscribeAvailability,
  },
}));
vi.mock("../../../services/embedFullscreenController", () => fullscreenMocks);
vi.mock("../../../services/embedPreviewRegistry", () => ({
  embedPreviewRegistry: previewRegistryMocks,
}));

async function flush(target?: HTMLElement): Promise<void> {
  await tick();
  if (!target) return;
  await vi.waitFor(() => {
    expect(target.querySelector('[data-testid="embeds-map-view"]')?.getAttribute('data-loading')).toBe('false');
  });
}

describe("EmbedsMapView", () => {
  beforeEach(() => {
    embedResolverMocks.resolveEmbed.mockReset();
    embedResolverMocks.decodeToonContent.mockReset();
    embedStoreMocks.resolveByRefDeep.mockReset();
    fullscreenMocks.dispatchEmbedFullscreen.mockReset();
    previewRegistryMocks.resolve.mockReset();
    delete (globalThis as typeof globalThis & { __emitMapViewRefIndex?: (value: number) => void }).__emitMapViewRefIndex;
    delete (globalThis as typeof globalThis & { __emitMapViewEmbedAvailability?: (value: number) => void }).__emitMapViewEmbedAvailability;

    previewRegistryMocks.resolve.mockImplementation(async ({ embedId, decodedContent, onFullscreen }: {
      embedId: string;
      decodedContent: Record<string, unknown>;
      onFullscreen: () => void;
    }) => {
      const route = [decodedContent.origin, decodedContent.destination]
        .filter((value): value is string => typeof value === "string")
        .join(" -> ");
      const skillName = String(decodedContent.displayName ?? decodedContent.title ?? (route || embedId));
      return {
        component: UnifiedEmbedPreview,
        props: {
          id: embedId,
          appId: String(decodedContent.app_id ?? "maps"),
          skillId: String(decodedContent.skill_id ?? "result"),
          status: "finished",
          skillName,
          showStatus: false,
          showSkillIcon: false,
          onFullscreen,
        },
      };
    });

    embedStoreMocks.resolveByRefDeep.mockImplementation(async (ref: string) => {
      const map: Record<string, string> = {
        "events-search-abcdef": "source-embed-id",
        "travel-search-routes": "travel-source-id",
        "event-one-111111": "event-one-id",
        "event-two-222222": "event-two-id",
        "event-online-333333": "event-online-id",
        "place-two-222222": "place-two-id",
        "train-one-111111": "train-one-id",
        "train-two-222222": "train-two-id",
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
      if (embedId === "travel-source-id") {
        return {
          embed_id: embedId,
          type: "app_skill_use",
          status: "finished",
          content: "travel-source-content",
          embed_ids: ["train-one-111111", "train-two-222222"],
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
      if (embedId === "event-two-id") {
        return {
          embed_id: embedId,
          type: "events-event",
          status: "finished",
          content: "event-two-content",
          createdAt: 1,
          updatedAt: 1,
        };
      }
      if (embedId === "event-online-id") {
        return {
          embed_id: embedId,
          type: "events-event",
          status: "finished",
          content: "event-online-content",
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
      if (embedId === "train-one-id") {
        return {
          embed_id: embedId,
          type: "connection",
          status: "finished",
          content: "train-one-content",
          createdAt: 1,
          updatedAt: 1,
        };
      }
      if (embedId === "train-two-id") {
        return {
          embed_id: embedId,
          type: "connection",
          status: "finished",
          content: "train-two-content",
          createdAt: 1,
          updatedAt: 1,
        };
      }
      return null;
    });

    embedResolverMocks.decodeToonContent.mockImplementation(async (content: string) => {
      if (content === "source-content") return { app_id: "events", skill_id: "search" };
      if (content === "travel-source-content") return { app_id: "travel", skill_id: "search_connections" };
      if (content === "event-content") {
        return {
          app_id: "events",
          skill_id: "event",
          title: "AI Founders Meetup",
          date_start: "2026-08-01T18:00:00Z",
          venue_lat: 52.530247,
          venue_lon: 13.411047,
          venue: { address: "Berlin" },
        };
      }
      if (content === "event-two-content") {
        return {
          app_id: "events",
          skill_id: "event",
          title: "AI Builders Night",
          date_start: "2026-08-01T20:00:00Z",
          venue_lat: 52.5004,
          venue_lon: 13.4252,
          venue: { address: "Berlin" },
        };
      }
      if (content === "event-online-content") {
        return {
          app_id: "events",
          skill_id: "event",
          title: "Global AI Livestream",
          date_start: "2026-08-01T21:00:00Z",
          event_type: "ONLINE",
          venue_name: "Online event",
          venue_lat: -8.521147,
          venue_lon: 179.1962,
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
      if (content === "train-one-content") {
        return {
          app_id: "travel",
          skill_id: "search_connections",
          transport_method: "train",
          source_provider: "deutsche_bahn",
          origin: "Bonn Hbf",
          destination: "Muenchen Hbf",
          departure: "2026-08-12 08:27",
          arrival: "2026-08-12 17:56",
          duration: "9h 29m",
          stops: 5,
          legs: [{
            segments: [
              {
                carrier: "RB",
                line: "RB26",
                mode: "train",
                fare_coverage: "pass_covered",
                departure_latitude: 50.731964,
                departure_longitude: 7.096678,
                arrival_latitude: 50.00124,
                arrival_longitude: 8.258453,
              },
              {
                carrier: "RE",
                line: "RE8",
                mode: "train",
                fare_coverage: "pass_covered",
                departure_latitude: 50.00124,
                departure_longitude: 8.258453,
                arrival_latitude: 49.7913,
                arrival_longitude: 9.9534,
              },
            ],
            layovers: [{ airport: "Mainz Hbf", duration: "8m", duration_minutes: 8, meets_min_transfer: false }],
          }],
        };
      }
      if (content === "train-two-content") {
        return {
          app_id: "travel",
          skill_id: "search_connections",
          transport_method: "train",
          source_provider: "flix",
          origin: "Bonn Hbf",
          destination: "Muenchen Hbf",
          departure: "2026-08-12T08:56:00+02:00",
          arrival: "2026-08-12T18:19:00+02:00",
          duration: "9h 23m",
          stops: 3,
          line: "RE5",
          carrier: "RE",
          fare_coverage: "pass_covered",
          legs_0_segments_0_departure_latitude: 50.731964,
          legs_0_segments_0_departure_longitude: 7.096678,
          legs_0_segments_0_arrival_latitude: 50.350777,
          legs_0_segments_0_arrival_longitude: 7.588343,
          legs_0_segments_1_departure_latitude: 50.350777,
          legs_0_segments_1_departure_longitude: 7.588343,
          legs_0_segments_1_arrival_latitude: 48.1402,
          legs_0_segments_1_arrival_longitude: 11.5583,
          legs_0_layovers_0_airport: "Koblenz Hbf",
          legs_0_layovers_0_duration: "22m",
          legs_0_layovers_0_duration_minutes: 22,
          legs_0_layovers_0_meets_min_transfer: true,
        };
      }
      return null;
    });
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  it("loads source children, sorts highlights first, and derives filters", async () => {
    const target = document.createElement("div");
    document.body.appendChild(target);

    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-1",
        title: "Berlin AI events",
        embedRefs: [],
        sourceRefs: ["embed:events-search-abcdef"],
        highlightRefs: ["place-two-222222"],
      },
    });

    await flush(target);

    const cards = Array.from(target.querySelectorAll('[data-testid="embeds-map-view-card"]'));
    expect(cards).toHaveLength(2);
    expect(target.querySelector('[data-testid="embeds-map-view-carousel"]')).not.toBeNull();
    expect(target.querySelectorAll('[data-testid="embed-preview"]')).toHaveLength(2);
    expect(cards[0].querySelector('[data-testid="embed-preview"]')).not.toBeNull();
    expect(cards[1].querySelector('[data-testid="embed-preview"]')).not.toBeNull();
    expect(cards[0].textContent).toContain("Factory Berlin");
    expect(cards[0].classList.contains("highlighted")).toBe(true);
    expect(target.querySelector('[data-testid="embeds-map-view-map"]')?.textContent).not.toContain("Referenced embeds do not expose coordinates yet.");
    expect(target.querySelector('[data-testid="embeds-map-view-count"]')?.textContent).toContain("2 shown");
    expect(target.querySelector('[data-testid="embeds-map-view-filter-button"]')?.textContent).toContain("Filter");
    expect(target.textContent).not.toContain("Map view");
    expect(target.textContent).not.toContain("Berlin AI events");
    expect(embedResolverMocks.resolveEmbed).toHaveBeenCalledWith("source-embed-id");
    expect(embedResolverMocks.resolveEmbed).toHaveBeenCalledWith("event-one-id");
    expect(embedResolverMocks.resolveEmbed).toHaveBeenCalledWith("place-two-id");
    expect(fullscreenMocks.dispatchEmbedFullscreen).not.toHaveBeenCalled();

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  it("selects entries locally in fullscreen mode without opening child fullscreens", async () => {
    const target = document.createElement("div");
    document.body.appendChild(target);

    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-select",
        title: "Berlin AI events",
        embedRefs: [],
        sourceRefs: ["events-search-abcdef"],
        highlightRefs: [],
        interactionMode: "select",
      },
    });

    await flush(target);

    const cards = Array.from(target.querySelectorAll<HTMLElement>('[data-testid="embeds-map-view-card"]'));
    expect(cards).toHaveLength(2);
    expect(cards[0].dataset.selected).toBe("false");

    const firstInteractiveCard = cards[0].querySelector<HTMLElement>('[data-testid="embed-preview"], [data-testid="embeds-map-view-fallback-card"]');
    expect(firstInteractiveCard).not.toBeNull();
    firstInteractiveCard!.click();
    await tick();

    expect(cards[0].dataset.selected).toBe("true");
    expect(fullscreenMocks.dispatchEmbedFullscreen).not.toHaveBeenCalled();

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  it("opens a top-right filter menu and dims non-hovered entries", async () => {
    const target = document.createElement("div");
    document.body.appendChild(target);

    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-2",
        title: "Berlin AI events",
        embedRefs: [],
        sourceRefs: ["events-search-abcdef"],
        highlightRefs: ["place-two-222222"],
      },
    });

    await flush(target);

    const filterButton = target.querySelector<HTMLButtonElement>('[data-testid="embeds-map-view-filter-button"]');
    expect(filterButton).not.toBeNull();
    expect(filterButton?.dataset.icon).toBe("filter");
    filterButton!.click();
    await tick();

    const filterMenu = target.querySelector('[data-testid="embeds-map-view-filter-menu"]');
    expect(filterButton?.dataset.icon).toBe("close");
    expect(filterMenu?.getAttribute("data-layout")).toBe("results-panel");
    expect(filterMenu?.textContent).toContain("All results");
    expect(filterMenu?.textContent).toContain("event");
    expect(filterMenu?.textContent).toContain("place");
    expect(target.querySelector('[data-testid="embeds-map-view-list"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="embeds-results-view-pane"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="embeds-map-view-list"]')?.closest('[aria-hidden]')?.getAttribute("aria-hidden")).toBe("true");

    filterButton!.click();
    await tick();
    expect(filterButton?.dataset.icon).toBe("filter");

    const cards = Array.from(target.querySelectorAll<HTMLButtonElement>('[data-testid="embeds-map-view-card"]'));
    cards[1].dispatchEvent(new Event("pointerenter"));
    await tick();

    expect(cards[1].dataset.hovered).toBe("true");
    expect(cards[0].dataset.dimmed).toBe("true");

    cards[1].dispatchEvent(new Event("pointerleave"));
    await tick();
    expect(cards[0].dataset.dimmed).toBe("false");

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  it("switches from the map state to the full weekly calendar state", async () => {
    const target = document.createElement("div");
    document.body.appendChild(target);

    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-tabs",
        title: "Berlin AI events",
        embedRefs: [],
        sourceRefs: ["events-search-abcdef"],
        highlightRefs: [],
      },
    });

    await flush(target);

    expect(target.querySelector('[data-testid="embeds-results-view-tabs"]')?.textContent).toContain("Map");
    expect(target.querySelector('[data-testid="embeds-results-view-tabs"]')?.textContent).toContain("Calendar");
    expect(target.querySelector('[data-testid="embeds-results-view-tab-map-icon"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="embeds-results-view-tab-calendar-icon"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="embeds-results-view-tab-list"]')).toBeNull();
    expect(target.querySelectorAll('[data-testid="embeds-map-view-card"]')).toHaveLength(2);
    expect(target.querySelector('[data-testid="embeds-map-view-map"]')).not.toBeNull();

    target.querySelector<HTMLButtonElement>('[data-testid="embeds-results-view-tab-calendar"]')?.click();
    await tick();

    expect(target.querySelector('[data-testid="embeds-results-view-pane"]')?.getAttribute("data-active-tab")).toBe("calendar");
    expect(target.querySelectorAll('[data-testid="embeds-map-view-card"]')).toHaveLength(0);
    expect(target.querySelector('[data-testid="embeds-map-view-map"]')).toBeNull();
    expect(target.querySelector('[data-testid="embeds-results-view-calendar-week"]')).not.toBeNull();
    expect(target.querySelectorAll('[data-testid="embeds-results-view-calendar-day"]')).toHaveLength(7);
    expect(target.querySelector('[data-testid="embeds-results-view-calendar-week-label"]')?.textContent).toContain("Jul 27");
    const calendarItems = target.querySelectorAll('[data-testid="embeds-results-view-calendar-item"]');
    expect(calendarItems).toHaveLength(1);
    expect(calendarItems[0].textContent).toContain("AI Founders Meetup");

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  it("labels event and appointment start filters as time, not departure time", async () => {
    const target = document.createElement("div");
    document.body.appendChild(target);

    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-event-times",
        title: "Berlin AI events",
        embedRefs: ["event-one-111111", "event-two-222222"],
        sourceRefs: [],
        highlightRefs: [],
      },
    });

    await flush(target);

    const filterButton = target.querySelector<HTMLButtonElement>('[data-testid="embeds-map-view-filter-button"]');
    expect(filterButton).not.toBeNull();
    filterButton!.click();
    await tick();

    const filterMenu = target.querySelector('[data-testid="embeds-map-view-filter-menu"]');
    expect(filterMenu?.textContent).toContain("Time");
    expect(filterMenu?.textContent).not.toContain("Departure time");
    expect(filterMenu?.textContent).not.toContain("Arrival time");

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  it("does not map online event placeholder coordinates", async () => {
    const target = document.createElement("div");
    document.body.appendChild(target);

    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-online-events",
        title: "Berlin AI events",
        embedRefs: ["event-one-111111", "event-online-333333"],
        sourceRefs: [],
        highlightRefs: [],
      },
    });

    await flush(target);

    expect(target.querySelectorAll('[data-testid="embeds-map-view-card"]')).toHaveLength(2);
    expect(target.textContent).toContain("Global AI Livestream");
    expect(target.querySelector('[data-testid="embeds-map-view-map"]')?.getAttribute("data-marker-count")).toBe("1");
    expect(target.querySelector('[data-testid="embeds-map-view-map"]')?.textContent).not.toContain("Referenced embeds do not expose coordinates yet.");

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  it("draws multiple travel connection routes from structured and flat segment coordinates", async () => {
    const target = document.createElement("div");
    document.body.appendChild(target);

    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-routes",
        title: "Bonn to Munich routes",
        embedRefs: [],
        sourceRefs: ["travel-search-routes"],
        highlightRefs: ["train-two-222222"],
      },
    });

    await flush(target);

    const cards = Array.from(target.querySelectorAll('[data-testid="embeds-map-view-card"]'));
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain("Bonn Hbf");
    expect(cards[0].textContent).toContain("Muenchen Hbf");
    expect(cards[0].classList.contains("highlighted")).toBe(true);
    expect(cards[0].querySelector('[data-testid="embed-preview"]')?.getAttribute("style")).toContain("height: 200px");
    expect(target.textContent).not.toContain("Search connections");
    expect(target.textContent).not.toContain("0 connections");
    const map = target.querySelector('[data-testid="embeds-map-view-map"]');
    expect(map?.getAttribute("data-route-count")).toBe("2");
    expect(map?.getAttribute("data-marker-count")).toBe("5");
    expect(map?.getAttribute("data-endpoint-marker-count")).toBe("3");
    expect(map?.getAttribute("data-stop-marker-count")).toBe("2");
    expect(target.querySelector('[data-testid="embeds-map-view-map"]')?.textContent).not.toContain("Referenced embeds do not expose coordinates yet.");

    target.querySelector<HTMLButtonElement>('[data-testid="embeds-results-view-tab-calendar"]')?.click();
    await tick();
    expect(target.querySelectorAll('[data-testid="embeds-results-view-calendar-item"]')).toHaveLength(2);

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  it("derives route filters and applies them without re-decoding entries", async () => {
    const target = document.createElement("div");
    document.body.appendChild(target);

    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-route-filters",
        title: "Bonn to Munich routes",
        embedRefs: [],
        sourceRefs: ["travel-search-routes"],
        highlightRefs: [],
      },
    });

    await flush(target);
    const decodeCountAfterLoad = embedResolverMocks.decodeToonContent.mock.calls.length;

    const filterButton = target.querySelector<HTMLButtonElement>('[data-testid="embeds-map-view-filter-button"]');
    expect(filterButton).not.toBeNull();
    filterButton!.click();
    await tick();

    const filterMenu = target.querySelector('[data-testid="embeds-map-view-filter-menu"]');
    expect(filterMenu?.getAttribute("role")).toBe("region");
    expect(filterMenu?.textContent).toContain("Departure time");
    expect(filterMenu?.textContent).toContain("Duration");
    expect(filterMenu?.textContent).toContain("Transfer time");
    expect(filterMenu?.textContent).toContain("Stops");
    expect(filterMenu?.textContent).toContain("Provider");
    expect(filterMenu?.textContent).toContain("Train line");

    const transferMin = target.querySelector<HTMLInputElement>('[data-testid="embeds-map-view-filter-transferMinutes-min"]');
    expect(transferMin).not.toBeNull();
    expect(transferMin?.getAttribute("aria-label")).toBe("Transfer time minimum");
    transferMin!.value = "15";
    transferMin!.dispatchEvent(new Event("input", { bubbles: true }));
    await tick();

    expect(target.querySelector('[data-testid="embeds-map-view-filter-summary"]')?.textContent).toContain("1 of 2 results remain");
    filterButton!.click();
    await tick();

    let cards = Array.from(target.querySelectorAll('[data-testid="embeds-map-view-card"]'));
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain("Bonn Hbf");
    expect(cards[0].textContent).toContain("Muenchen Hbf");
    expect(target.querySelector('[data-testid="embeds-map-view-map"]')?.getAttribute("data-route-count")).toBe("1");

    filterButton!.click();
    await tick();
    target.querySelector<HTMLButtonElement>('[data-testid="embeds-map-view-clear-filters"]')?.click();
    await tick();

    target.querySelector<HTMLButtonElement>('[data-testid="embeds-map-view-option-provider-deutsche_bahn"]')?.click();
    await tick();

    expect(target.querySelector('[data-testid="embeds-map-view-filter-summary"]')?.textContent).toContain("1 of 2 results remain");
    filterButton!.click();
    await tick();
    cards = Array.from(target.querySelectorAll('[data-testid="embeds-map-view-card"]'));
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain("Bonn Hbf");
    expect(cards[0].textContent).toContain("Muenchen Hbf");
    expect(target.querySelector('[data-testid="embeds-map-view-map"]')?.getAttribute("data-route-count")).toBe("1");
    expect(embedResolverMocks.decodeToonContent.mock.calls.length).toBe(decodeCountAfterLoad);

    filterButton!.click();
    await tick();
    target.querySelector<HTMLButtonElement>('[data-testid="embeds-map-view-clear-filters"]')?.click();
    await tick();
    filterButton!.click();
    await tick();
    expect(target.querySelectorAll('[data-testid="embeds-map-view-card"]')).toHaveLength(2);

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  it("does not re-resolve ready entries for unrelated ref-index bumps", async () => {
    const target = document.createElement("div");
    document.body.appendChild(target);

    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-ref-index",
        title: "Bonn to Munich routes",
        embedRefs: [],
        sourceRefs: ["travel-search-routes"],
        highlightRefs: [],
      },
    });

    await flush(target);
    const resolveCallsAfterLoad = embedResolverMocks.resolveEmbed.mock.calls.length;
    const emitRefIndex = (globalThis as typeof globalThis & { __emitMapViewRefIndex?: (value: number) => void }).__emitMapViewRefIndex;
    expect(emitRefIndex).toBeTypeOf("function");

    emitRefIndex?.(1);
    await flush(target);

    expect(embedResolverMocks.resolveEmbed.mock.calls.length).toBe(resolveCallsAfterLoad);

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=billing.credits.retryable-completion-safe
  it("retries source refs when the ref index changes during the initial load", async () => {
    const defaultResolveEmbed = embedResolverMocks.resolveEmbed.getMockImplementation();
    let releaseFirstSourceResolution: () => void = () => undefined;
    const firstSourceResolution = new Promise<void>((resolve) => {
      releaseFirstSourceResolution = resolve;
    });
    let sourceAttempts = 0;
    embedResolverMocks.resolveEmbed.mockImplementation(async (embedId: string) => {
      if (embedId === "source-embed-id" && sourceAttempts++ === 0) {
        await firstSourceResolution;
        return null;
      }
      return defaultResolveEmbed?.(embedId) ?? null;
    });

    const target = document.createElement("div");
    document.body.appendChild(target);
    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-initial-ref-index-race",
        title: "Berlin AI events",
        embedRefs: [],
        sourceRefs: ["events-search-abcdef"],
        highlightRefs: [],
      },
    });

    await flush();
    const emitRefIndex = (globalThis as typeof globalThis & { __emitMapViewRefIndex?: (value: number) => void }).__emitMapViewRefIndex;
    expect(emitRefIndex).toBeTypeOf("function");

    emitRefIndex?.(1);
    releaseFirstSourceResolution();
    await flush(target);

    expect(target.querySelectorAll('[data-testid="embeds-map-view-card"]')).toHaveLength(2);
    expect(target.querySelector('[data-testid="embeds-map-view-count"]')?.textContent).toContain("2 shown");
    expect(target.querySelector('[data-testid="embeds-map-view-map"]')?.textContent).not.toContain("Referenced embeds do not expose coordinates yet.");
    expect(target.textContent).not.toContain("Loading referenced embeds...");

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=billing.credits.retryable-completion-safe
  it("retries unresolved source refs when synced embeds become available", async () => {
    const defaultResolveEmbed = embedResolverMocks.resolveEmbed.getMockImplementation();
    let sourceAvailable = false;
    embedResolverMocks.resolveEmbed.mockImplementation(async (embedId: string) => {
      if (embedId === "source-embed-id" && !sourceAvailable) return null;
      return defaultResolveEmbed?.(embedId) ?? null;
    });

    const target = document.createElement("div");
    document.body.appendChild(target);
    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-embed-availability",
        title: "Berlin AI events",
        embedRefs: [],
        sourceRefs: ["events-search-abcdef"],
        highlightRefs: [],
      },
    });

    await flush(target);
    expect(target.textContent).toContain("Waiting for source results");

    sourceAvailable = true;
    const emitAvailability = (globalThis as typeof globalThis & { __emitMapViewEmbedAvailability?: (value: number) => void }).__emitMapViewEmbedAvailability;
    expect(emitAvailability).toBeTypeOf("function");
    emitAvailability?.(1);
    await flush(target);

    expect(target.querySelectorAll('[data-testid="embeds-map-view-card"][data-entry-status="ready"]')).toHaveLength(2);
    expect(target.textContent).not.toContain("Waiting for source results");
    expect(target.querySelector('[data-testid="embeds-map-view-map"]')?.getAttribute("data-marker-count")).not.toBe("0");

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  it("cancels one scheduled idle map hydration when unmounted", async () => {
    const originalRequestIdleCallback = globalThis.requestIdleCallback;
    const originalCancelIdleCallback = globalThis.cancelIdleCallback;
    const requestIdleCallback = vi.fn(() => 41);
    const cancelIdleCallback = vi.fn();
    Object.assign(globalThis, { requestIdleCallback, cancelIdleCallback });

    const target = document.createElement("div");
    document.body.appendChild(target);
    const component = mount(EmbedsMapView, {
      target,
      props: {
        id: "map-view-idle-cancel",
        title: "Berlin AI events",
        embedRefs: ["event-one-111111"],
        sourceRefs: [],
        highlightRefs: [],
      },
    });

    await flush(target);
    expect(requestIdleCallback).toHaveBeenCalledTimes(1);
    unmount(component);
    expect(cancelIdleCallback).toHaveBeenCalledWith(41);

    target.remove();
    Object.assign(globalThis, {
      requestIdleCallback: originalRequestIdleCallback,
      cancelIdleCallback: originalCancelIdleCallback,
    });
  });
});
