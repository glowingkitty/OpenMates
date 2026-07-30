// @vitest-environment jsdom
// frontend/packages/ui/src/components/embeds/__tests__/EmbedLeafletMap.test.ts
// Regression coverage for Leaflet/OpenStreetMap theme selection.
// The app-level UI theme is expressed via <html data-theme>, so map tiles must
// prefer that resolved value over OS prefers-color-scheme.
// Architecture: docs/architecture/embeds.md

import { mount, tick, unmount } from "svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EmbedLeafletMap from "../EmbedLeafletMap.svelte";

const leafletMocks = vi.hoisted(() => {
  const mapInstance = {
    fitBounds: vi.fn(),
    invalidateSize: vi.fn(),
    panBy: vi.fn(),
    remove: vi.fn(),
  };
  const markerInstance = {
    bindTooltip: vi.fn(),
  };
  return {
    mapInstance,
    tileLayer: vi.fn(() => ({ addTo: vi.fn() })),
    map: vi.fn(() => mapInstance),
    control: {
      zoom: vi.fn(() => ({ addTo: vi.fn() })),
    },
    divIcon: vi.fn(() => ({})),
    marker: vi.fn(() => ({ addTo: vi.fn(() => markerInstance) })),
    polyline: vi.fn(() => ({ addTo: vi.fn() })),
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
    vi.clearAllMocks();
  });

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
});
