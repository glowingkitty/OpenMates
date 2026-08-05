// frontend/packages/ui/src/components/enter_message/extensions/__tests__/streamingNodeViewIdentity.test.ts
// Defines semantic identity rules for streamed preview and result-view NodeViews.
// Presentation-only carousel changes must update props without remounting content.
// Result views remount only when their normalized descriptor identity changes.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { describe, expect, it } from "vitest";
import {
  hasStableLargePreviewIdentity,
  hasStableResultViewIdentity,
} from "../streamingNodeIdentity";

describe("streaming NodeView identity", () => {
  it("keeps a large preview mounted when only carousel metadata changes", () => {
    const previous = {
      embedRef: "event-one-ref",
      embedId: "event-one-id",
      appId: "events",
      carouselIndex: 0,
      carouselTotal: 1,
      runRef: "event-one-ref",
    };
    const next = {
      ...previous,
      carouselIndex: 1,
      carouselTotal: 3,
      runRef: "new-first-ref",
    };

    expect(hasStableLargePreviewIdentity(previous, next)).toBe(true);
    expect(hasStableLargePreviewIdentity(previous, { ...next, embedId: "other-id" })).toBe(false);
  });

  it("uses normalized result-view refs rather than array identity", () => {
    const previous = {
      id: "view-1",
      mapEmbedRefs: ["event-one", "event-two"],
      mapSourceRefs: ["search-parent"],
      mapHighlightRefs: ["event-two"],
    };
    const equivalent = {
      ...previous,
      mapEmbedRefs: [...previous.mapEmbedRefs],
      mapSourceRefs: [...previous.mapSourceRefs],
      mapHighlightRefs: [...previous.mapHighlightRefs],
    };

    expect(hasStableResultViewIdentity(previous, equivalent)).toBe(true);
    expect(
      hasStableResultViewIdentity(previous, {
        ...equivalent,
        mapEmbedRefs: ["event-one", "event-three"],
      }),
    ).toBe(false);
  });
});
