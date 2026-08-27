// frontend/packages/openmates-cli/tests/uploadService.test.ts
// Verifies the identity boundary between isolated uploads and stored chat embeds.
// Cleanup joins upload_files to embeds by the upload server's authoritative ID.
// This test intentionally uses no network or package-specific fixtures.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { it } from "node:test";

import { adoptUploadEmbedId } from "../src/uploadService.ts";


// contract-test: supporting surface=cli assertions=storage.replication.active-write-durable-outbox
it("adopts the upload server embed ID for durable cleanup joins", () => {
  const embed = { embedId: "local-pre-upload-id" };

  adoptUploadEmbedId(embed, "authoritative-upload-id");

  assert.equal(embed.embedId, "authoritative-upload-id");
});


// contract-test: supporting surface=cli assertions=storage.replication.active-write-durable-outbox
it("adopts authoritative IDs at every persisted upload call site", () => {
  const cliSource = readFileSync(new URL("../src/cli.ts", import.meta.url), "utf8");
  const clientSource = readFileSync(new URL("../src/client.ts", import.meta.url), "utf8");

  assert.match(
    cliSource,
    /const uploadResult = await uploadFile\(fe\.localPath, session\);\s+adoptUploadEmbedId\(fe\.embed, uploadResult\.embed_id\);/,
  );
  assert.match(
    clientSource,
    /const uploadResult = await uploadFile\(audioEmbed\.localPath, session\);\s+adoptUploadEmbedId\(audioEmbed\.embed, uploadResult\.embed_id\);/,
  );
});
