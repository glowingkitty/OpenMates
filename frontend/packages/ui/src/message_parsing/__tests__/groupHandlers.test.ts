// Unit tests for embed grouping behavior.
// Reference-only embeds represent existing synced uploads selected from search.
// They must stay as standalone references so deleting or splitting groups cannot
// cascade into deleting the underlying uploaded file.
// These tests exercise the public group-handler registry behavior.

import { describe, expect, it } from "vitest";
import { groupHandlerRegistry } from "../groupHandlers";
import type { EmbedNodeAttributes } from "../types";

describe("groupHandlerRegistry", () => {
  it("does not group reference-only embeds", () => {
    const first: EmbedNodeAttributes = {
      id: "file-a",
      type: "code-code",
      status: "finished",
      contentRef: "embed:file-a",
      referenceOnly: true,
    };
    const second: EmbedNodeAttributes = {
      id: "file-b",
      type: "code-code",
      status: "finished",
      contentRef: "embed:file-b",
    };

    expect(groupHandlerRegistry.canGroup(first, second)).toBe(false);
  });
});
