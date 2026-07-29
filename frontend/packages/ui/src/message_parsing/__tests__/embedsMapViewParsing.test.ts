// frontend/packages/ui/src/message_parsing/__tests__/embedsMapViewParsing.test.ts
// Parser contract for the virtual `embeds_map_view` message block.
// The map view is a lightweight presentation over existing embeds, not a
// persisted embed type, so these tests guard ref-only parsing and round trips.
// Spec: docs/specs/embeds-map-view/spec.yml

import { describe, expect, it } from "vitest";
import { parseEmbedNodes } from "../embedParsing";
import { parse_message } from "../parse_message";

describe("embeds_map_view parsing", () => {
  it("parses curated child refs and preserves order", () => {
    const markdown = `Here are the strongest matches:


\`\`\`embeds_map_view
title: Berlin AI events
embeds: ai-founders-meetup-7f3a91, llm-hack-night-22b8c0
\`\`\``;

    const [mapView] = parseEmbedNodes(markdown, "read");

    expect(mapView).toMatchObject({
      type: "embeds-map-view",
      status: "finished",
      title: "Berlin AI events",
      mapEmbedRefs: ["ai-founders-meetup-7f3a91", "llm-hack-night-22b8c0"],
      mapSourceRefs: [],
      mapHighlightRefs: [],
    });
  });

  it("parses source refs with highlighted child refs", () => {
    const markdown = `\`\`\`embeds_map_view
title: Munich to Zurich options
sources: travel-search-connections-12ab34
highlight: nightjet-munich-zurich-7abc12, db-ice-basel-9def34
\`\`\``;

    const [mapView] = parseEmbedNodes(markdown, "read");

    expect(mapView).toMatchObject({
      type: "embeds-map-view",
      title: "Munich to Zurich options",
      mapEmbedRefs: [],
      mapSourceRefs: ["travel-search-connections-12ab34"],
      mapHighlightRefs: ["nightjet-munich-zurich-7abc12", "db-ice-basel-9def34"],
    });
  });

  it("drops unsupported fields and duplicate refs", () => {
    const markdown = `\`\`\`embeds_map_view
title: Clinics near me
provider: paid-provider
filters: specialty=dermatology
embeds: clinic-one-111111, clinic-one-111111, clinic-two-222222
enrichment: travel.flight_details
\`\`\``;

    const [mapView] = parseEmbedNodes(markdown, "read");

    expect(mapView.mapEmbedRefs).toEqual(["clinic-one-111111", "clinic-two-222222"]);
    expect(mapView).not.toHaveProperty("provider");
    expect(mapView).not.toHaveProperty("filters");
    expect(mapView).not.toHaveProperty("enrichment");
  });

  it("turns the fenced block into a virtual embed node in unified parsing", () => {
    const doc = parse_message(
      `Intro\n\n\`\`\`embeds_map_view\ntitle: Berlin AI events\nembeds: one-111111\n\`\`\``,
      "read",
      { unifiedParsingEnabled: true, role: "assistant" },
    );

    const children = (doc.content ?? []).flatMap(
      (node: { content?: Array<{ type?: string; attrs?: { type?: string } }> }) => node.content ?? [],
    );
    const embedNode = children.find((node) => node.type === "embed" && node.attrs?.type === "embeds-map-view");

    expect(embedNode).toMatchObject({
      type: "embed",
      attrs: {
        type: "embeds-map-view",
        title: "Berlin AI events",
        mapEmbedRefs: ["one-111111"],
      },
    });
  });
});
