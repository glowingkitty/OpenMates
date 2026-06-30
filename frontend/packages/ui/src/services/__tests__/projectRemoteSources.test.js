/**
 * Project remote-source service helper tests.
 *
 * Purpose: verify virtual remote previews and source payload normalization
 * without browser state or real network calls.
 * Security: remote previews are virtual message-local data, not persisted embeds.
 * Run: node --test --experimental-strip-types src/services/__tests__/projectRemoteSources.test.js
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  buildProjectSourceCreatePayload,
  normalizeRemoteFilePreview,
} from "../projectRemoteSources.ts";

describe("Project remote source helpers", () => {
  it("builds non-mutating encrypted source payloads", () => {
    const payload = buildProjectSourceCreatePayload({
      sourceId: "source-1",
      sourceType: "remote_git_repository",
      encryptedDisplayName: "cipher-name",
      encryptedMetadata: "cipher-metadata",
      capabilities: ["read", "search", "import", "apply_patch"],
      timestamp: 100,
    });

    assert.deepEqual(payload, {
      source_id: "source-1",
      source_type: "remote_git_repository",
      encrypted_display_name: "cipher-name",
      encrypted_metadata: "cipher-metadata",
      capabilities: ["read", "search", "import"],
      status: "connected",
      created_at: 100,
      updated_at: 100,
    });
  });

  it("normalizes remote files into virtual embed-compatible previews", () => {
    const preview = normalizeRemoteFilePreview({
      sourceId: "source-1",
      path: "src/App.svelte",
      displayName: "App.svelte",
      language: "svelte",
      snippet: "<script>export let data;</script>",
      baseHash: "sha256:abc",
    });

    assert.equal(preview.isVirtual, true);
    assert.equal(preview.persistAsEmbed, false);
    assert.equal(preview.embed.type, "code-code");
    assert.equal(preview.embed.content.source_id, "source-1");
    assert.equal(preview.embed.content.path, "src/App.svelte");
    assert.equal(preview.embed.content.base_hash, "sha256:abc");
  });
});
