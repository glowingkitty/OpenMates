// frontend/packages/ui/src/__tests__/test-setup.test.ts
// Infrastructure coverage for shared Vitest environment shims.
//
// These tests verify behavior provided by `src/test-setup.ts` after Vitest
// loads it globally. They intentionally do not prove product contracts.
// contract-test-file: infrastructure

import { describe, expect, it } from "vitest";

describe("test setup shims", () => {
  it("provides Blob.arrayBuffer for generated file assertions", async () => {
    const blob = new Blob(["OpenMates"]);
    const bytes = new Uint8Array(await blob.arrayBuffer());

    expect(Array.from(bytes)).toEqual([79, 112, 101, 110, 77, 97, 116, 101, 115]);
  });
});
