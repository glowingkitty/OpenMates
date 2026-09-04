// @vitest-environment jsdom
// frontend/packages/ui/src/components/embeds/__tests__/EmbedLeafletMap.test.ts
// Regression coverage for Leaflet/OpenStreetMap theme selection.
// The app-level UI theme is expressed via <html data-theme>, so map tiles must
// prefer that resolved value over OS prefers-color-scheme.
// Architecture: docs/architecture/embeds.md

import { mount, tick, unmount } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import mapsMarkerIconUrl from "../../../../static/icons/maps.svg?url";
import EmbedLeafletMap from "../EmbedLeafletMap.svelte";

const leafletMocks = vi.hoisted(() => {
  const markerInstances: Array<{
    addTo: ReturnType<typeof vi.fn>;
    setOpacity: ReturnType<typeof vi.fn>;
    bindTooltip: ReturnType<typeof vi.fn>;
    eventHandlers: Record<string, () => void>;
    elementSetAttribute: ReturnType<typeof vi.fn>;
  }> = [];
  const mapInstance = {
    fitBounds: vi.fn(),
    invalidateSize: vi.fn(),
    on: vi.fn(),
    panBy: vi.fn(),
    remove: vi.fn(),
    setView: vi.fn(),
  };
  const tileClassToggle = vi.fn();
  return {
    mapInstance,
    markerInstances,
    tileClassToggle,
    tileLayer: vi.fn(() => {
      const layer = {
        addTo: vi.fn(() => layer),
        getContainer: vi.fn(() => ({ classList: { toggle: tileClassToggle } })),
        on: vi.fn(() => layer),
      };
      return layer;
    }),
    map: vi.fn(() => mapInstance),
    control: {
      zoom: vi.fn(() => ({ addTo: vi.fn(), getContainer: vi.fn(() => ({ setAttribute: vi.fn() })) })),
    },
    divIcon: vi.fn(() => ({})),
    layerGroup: vi.fn(() => {
      const layerGroup = {
        addTo: vi.fn(() => layerGroup),
        remove: vi.fn(),
      };
      return layerGroup;
    }),
    marker: vi.fn(() => {
      const elementSetAttribute = vi.fn();
      const eventHandlers: Record<string, () => void> = {};
      const markerInstance = {
        addTo: vi.fn(() => markerInstance),
        setOpacity: vi.fn(),
        bindTooltip: vi.fn(),
        on: vi.fn((event: string, callback: () => void) => {
          eventHandlers[event] = callback;
          return markerInstance;
        }),
        getElement: vi.fn(() => ({ setAttribute: elementSetAttribute })),
        eventHandlers,
        elementSetAttribute,
      };
      markerInstances.push(markerInstance);
      return markerInstance;
    }),
    polyline: vi.fn(() => {
      const line = {
        addTo: vi.fn(() => line),
        getElement: vi.fn(() => ({ setAttribute: vi.fn() })),
      };
      return line;
    }),
    latLngBounds: vi.fn(() => ({})),
  };
});

vi.mock("leaflet", () => ({ default: leafletMocks }));
vi.mock("leaflet/dist/leaflet.css", () => ({}));

function mockOsDarkMode(isDark: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn((query: string) => ({
      matches: query === "(prefers-color-scheme: dark)" ? isDark : false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

async function flushLeafletImport(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await tick();
}

describe("EmbedLeafletMap theme selection", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("style");
    leafletMocks.markerInstances.length = 0;
    vi.clearAllMocks();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.surface.semantic-parity
  it("uses manual light theme for tiles when the OS is dark", async () => {
    mockOsDarkMode(true);
    document.documentElement.setAttribute("data-theme", "light");
    const target = document.createElement("div");
    document.body.appendChild(target);

    const component = mount(EmbedLeafletMap, {
      target,
      props: {
        center: { lat: 52.52, lon: 13.405 },
        markers: [{ lat: 52.52, lon: 13.405, label: "Berlin" }],
      },
    });

    await flushLeafletImport();

    expect(leafletMocks.tileLayer).toHaveBeenCalledWith(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      expect.objectContaining({ className: "" }),
    );

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.surface.semantic-parity
  it("passes marker and path opacity to Leaflet while fitting geometry once on mount", async () => {
    mockOsDarkMode(false);
    const onMarkerSelect = vi.fn();
    const target = document.createElement("div");
    document.body.appendChild(target);

    const component = mount(EmbedLeafletMap, {
      target,
      props: {
        center: { lat: 52.52, lon: 13.405 },
        fitBounds: true,
        zoomControlPosition: "topleft",
        markers: [
          { lat: 52.52, lon: 13.405, label: "Dimmed marker", opacity: 0.5, testId: "endpoint-marker" },
          {
            lat: 52.53,
            lon: 13.41,
            label: "Mainz Hbf",
            opacity: 1,
            testId: "stop-marker",
            ref: "route-one",
            relatedRefs: ["route-one", "route-two"],
            selectionKey: "52.530000:13.410000",
            selected: true,
          },
        ],
        paths: [
          {
            opacity: 0.5,
            points: [
              { lat: 52.52, lon: 13.405 },
              { lat: 52.53, lon: 13.41 },
            ],
          },
        ],
        onMarkerSelect,
      },
    });

    await flushLeafletImport();

    expect(leafletMocks.mapInstance.fitBounds).toHaveBeenCalledTimes(1);
    expect(leafletMocks.control.zoom).toHaveBeenCalledWith({ position: "topleft" });
    expect(leafletMocks.markerInstances.map((marker) => marker.setOpacity.mock.calls[0]?.[0])).toEqual([
      0.5,
      1,
    ]);
    expect(leafletMocks.markerInstances[0].elementSetAttribute).toHaveBeenCalledWith("data-testid", "endpoint-marker");
    expect(leafletMocks.markerInstances[1].elementSetAttribute).toHaveBeenCalledWith("data-testid", "stop-marker");
    expect(leafletMocks.divIcon).toHaveBeenCalledWith(expect.objectContaining({
      html: expect.stringContaining('<img'),
    }));
    expect(leafletMocks.divIcon).toHaveBeenCalledWith(expect.objectContaining({
      html: expect.stringContaining(`src="${mapsMarkerIconUrl}"`),
    }));
    expect(leafletMocks.markerInstances[1].bindTooltip).toHaveBeenCalledWith("Mainz Hbf", expect.objectContaining({
      permanent: true,
      direction: "top",
    }));
    leafletMocks.markerInstances[1].eventHandlers.click();
    expect(onMarkerSelect).toHaveBeenCalledWith(
      "route-one",
      ["route-one", "route-two"],
      "52.530000:13.410000",
    );
    expect(leafletMocks.polyline).toHaveBeenCalledWith(
      [
        [52.52, 13.405],
        [52.53, 13.41],
      ],
      expect.objectContaining({ opacity: 0.5 }),
    );

    unmount(component);
    target.remove();
  });
});
