/*
 * Unit tests for VS Code bundled asset path normalization.
 *
 * Purpose: prevent SvelteKit asset paths from collapsing to top-level folders in
 * packaged VSIX webviews.
 * Architecture: covers the pure helper used before VS Code URI conversion.
 * Security: verifies query/hash stripping and traversal segment rejection.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { getSafeBundledAssetSegments } from "../src/assetPaths.ts";

test("bundled asset paths preserve nested SvelteKit asset segments", () => {
  assert.deepEqual(
    getSafeBundledAssetSegments("/_app/immutable/entry/start.ABC123.js"),
    ["_app", "immutable", "entry", "start.ABC123.js"],
  );
});

test("bundled asset paths strip query and hash suffixes", () => {
  assert.deepEqual(
    getSafeBundledAssetSegments("./_app/immutable/assets/app.css?v=123#theme"),
    ["_app", "immutable", "assets", "app.css"],
  );
});

test("bundled asset paths ignore dot and traversal segments", () => {
  assert.deepEqual(
    getSafeBundledAssetSegments("/../_app/./immutable/../entry/start.js"),
    ["_app", "immutable", "entry", "start.js"],
  );
});
