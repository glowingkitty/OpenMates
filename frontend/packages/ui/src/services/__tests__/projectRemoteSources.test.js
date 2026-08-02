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
  buildRemoteFileUploadCandidate,
  buildProjectSourceCreatePayload,
  buildVirtualRemoteFullscreenDetail,
  normalizeRemoteFilePreview,
} from "../projectRemoteSources.ts";
import {
  ProjectRemoteAccessReplayGuard,
  createProjectRemoteAccessHandshake,
  deriveProjectRemoteAccessSessionKey,
  openProjectRemoteAccessEnvelope,
} from "../projectRemoteAccessCrypto.ts";

const cryptoIdentity = {
  ownerId: "owner-1",
  projectId: "project-1",
  sourceId: "source-1",
  sourceSessionId: "session-1",
  requestingClientId: "browser-1",
  keyEpoch: 1,
};

describe("Project remote source helpers", () => {
  it("derives the same authenticated browser and CLI peer key", async () => {
    const projectKey = crypto.getRandomValues(new Uint8Array(32));
    const requester = await createProjectRemoteAccessHandshake(projectKey, cryptoIdentity, "requester");
    const source = await createProjectRemoteAccessHandshake(projectKey, cryptoIdentity, "source");
    const requesterKey = await deriveProjectRemoteAccessSessionKey(
      projectKey,
      cryptoIdentity,
      "requester",
      requester.privateKey,
      requester.handshake,
      source.handshake,
    );
    const sourceKey = await deriveProjectRemoteAccessSessionKey(
      projectKey,
      cryptoIdentity,
      "source",
      source.privateKey,
      source.handshake,
      requester.handshake,
    );
    assert.deepEqual(requesterKey, sourceKey);
  });

  it("rejects tampered remote result envelopes", async () => {
    const projectKey = crypto.getRandomValues(new Uint8Array(32));
    const requester = await createProjectRemoteAccessHandshake(projectKey, cryptoIdentity, "requester");
    const source = await createProjectRemoteAccessHandshake(projectKey, cryptoIdentity, "source");
    const requesterKey = await deriveProjectRemoteAccessSessionKey(
      projectKey,
      cryptoIdentity,
      "requester",
      requester.privateKey,
      requester.handshake,
      source.handshake,
    );
    await assert.rejects(
      () => openProjectRemoteAccessEnvelope(
        requesterKey,
        cryptoIdentity,
        "request-1",
        "result",
        { version: 1, nonce: "invalid", ciphertext: "invalid" },
        new ProjectRemoteAccessReplayGuard(),
      ),
      /invalid remote-access key or envelope field|envelope authentication failed/,
    );
  });

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
      displayName: "../bad<name>.svelte",
      language: "svelte",
      snippet: "<script>export let data;</script>",
      baseHash: "sha256:abc",
      sizeBytes: 512,
      lineCount: 20,
      mtime: "2026-06-30T12:00:00Z",
      contentHash: "sha256:content",
      gitStatus: "clean",
      previewPolicy: "first_40_lines",
      safetyFlags: ["safe_path"],
    });

    assert.equal(preview.isVirtual, true);
    assert.equal(preview.persistAsEmbed, false);
    assert.equal(preview.embed.type, "code-code");
    assert.equal(preview.embed.content.source_id, "source-1");
    assert.equal(preview.embed.content.path, "src/App.svelte");
    assert.equal(preview.embed.content.base_hash, "sha256:abc");
    assert.equal(preview.embed.content.line_count, 20);
    assert.equal(preview.embed.content.content_hash, "sha256:content");
    assert.deepEqual(preview.embed.content.safety_flags, ["safe_path"]);
  });

  it("converts only explicit virtual previews into upload candidates with encrypted-item metadata", async () => {
    const preview = normalizeRemoteFilePreview({
      sourceId: "source-1",
      path: "src/App.svelte",
      displayName: "../bad<name>.svelte",
      remoteItemId: "item-1",
      language: "svelte",
      snippet: "<script>export let preview;</script>",
      baseHash: "sha256:abc",
      sizeBytes: 1024,
      lineCount: 42,
      mtime: "2026-06-30T12:00:00Z",
      contentHash: "sha256:content",
      gitStatus: "modified",
      previewPolicy: "first_40_lines",
      safetyFlags: ["safe_path"],
    });

    const candidate = buildRemoteFileUploadCandidate({
      preview,
      content: "<script>export let fullFile;</script>",
    });

    assert.equal(candidate.file.name, "bad_name_.svelte");
    assert.equal(await candidate.file.text(), "<script>export let fullFile;</script>");
    assert.deepEqual(candidate.metadata, {
      source_id: "source-1",
      remote_path: "src/App.svelte",
      remote_base_hash: "sha256:abc",
      remote_content_hash: "sha256:content",
      remote_mtime: "2026-06-30T12:00:00Z",
      remote_git_status: "modified",
      safety_flags: ["safe_path"],
      imported_from_remote_source: true,
    });
  });

  it("builds virtual fullscreen details without requiring a persisted embed", () => {
    const preview = normalizeRemoteFilePreview({
      sourceId: "source-1",
      path: "src/App.svelte",
      displayName: "App.svelte",
      language: "svelte",
      snippet: "<script>export let data;</script>",
    });

    const detail = buildVirtualRemoteFullscreenDetail(preview);

    assert.equal(detail.embedId, "remote:source-1:src/App.svelte");
    assert.equal(detail.embedType, "code-code");
    assert.equal(detail.attrs.virtual, true);
    assert.equal(detail.attrs.contentRef, "remote:source-1:src/App.svelte");
    assert.equal(detail.decodedContent.source_id, "source-1");
    assert.equal(detail.embedData.app_id, "code");
  });

  it("rejects unbounded remote preview metadata before it reaches embed UI", () => {
    assert.throws(
      () => normalizeRemoteFilePreview({
        sourceId: "source-1",
        path: "src/App.svelte",
        displayName: "App.svelte",
        snippet: "x".repeat(20_001),
      }),
      /bounded preview limit/,
    );
  });

  it("bounds and sanitizes remote display names before using them as upload filenames", () => {
    const preview = normalizeRemoteFilePreview({
      sourceId: "source-1",
      path: "src/App.ts",
      displayName: `nested/\u202E${"x".repeat(220)}.ts`,
      snippet: "export {};",
    });

    const candidate = buildRemoteFileUploadCandidate({ preview, content: "export {};" });

    assert.equal(candidate.file.name.length, 180);
    assert.ok(!candidate.file.name.includes("\u202E"));
  });
});
