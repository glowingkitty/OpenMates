import assert from "node:assert/strict";
import test from "node:test";

import { capacityReplayMarker } from "../src/capacityReplayMarker.js";

// contract-test: supporting surface=cli assertions=storage.validation.synthetic-capacity
test("capacity marker is available only for isolated replay", () => {
  const marker = "<<<TEST_LIVE_MOCK:storage_capacity_v1>>>";
  assert.equal(capacityReplayMarker(marker, "http://localhost:8000", true), marker);
  assert.equal(capacityReplayMarker(undefined, "https://api.openmates.org", false), undefined);
  assert.throws(() => capacityReplayMarker(marker, "https://api.openmates.org", true));
  assert.throws(() => capacityReplayMarker(marker, "http://localhost:8000", false));
  assert.throws(() => capacityReplayMarker("<<<TEST_LIVE_RECORD:storage_capacity_v1>>>", "http://localhost:8000", true));
});
