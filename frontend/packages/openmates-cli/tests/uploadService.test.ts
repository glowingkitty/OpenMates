// frontend/packages/openmates-cli/tests/uploadService.test.ts
// Verifies the identity boundary between isolated uploads and stored chat embeds.
// Cleanup joins upload_files to embeds by the upload server's authoritative ID.
// Upload privacy checks use synthetic local files and mocked multipart requests.

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { it } from "node:test";
import JSZip from "jszip";
import { PDFDocument } from "pdf-lib";
import sharp from "sharp";

import { adoptUploadEmbedId, transcribeUploadedAudio, uploadFile, uploadProfileImage, uploadTeamProfileImage } from "../src/uploadService.ts";
import type { UploadFileResponse } from "../src/uploadService.ts";
import type { OpenMatesSession } from "../src/storage.ts";


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

const session = { apiUrl: "http://localhost:8000", cookies: { auth_refresh_token: "test" } } as OpenMatesSession;

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
it("retains the source filename in downstream transcription requests", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_input, init) => {
    const body = JSON.parse(String(init?.body));
    assert.equal(body.requests[0].filename, "private-recorder.wav");
    assert.equal(body.requests[0].mime_type, "audio/wav");
    return Response.json({ data: { results: [{ id: "test", results: [{ transcript: "hello" }] }] } });
  };
  try {
    const uploaded = { embed_id: "test", content_type: "audio/wav", files: { original: { s3_key: "test" } } } as UploadFileResponse;
    const result = await transcribeUploadedAudio(uploaded, "private-recorder.wav", session);
    assert.equal(result.transcript, "hello");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

async function withUploadFile(
  name: string,
  bytes: Uint8Array,
  run: (path: string) => Promise<void>,
): Promise<void> {
  const directory = mkdtempSync(join(tmpdir(), "openmates-upload-privacy-"));
  try {
    const path = join(directory, name);
    writeFileSync(path, bytes);
    await run(path);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

async function interceptUpload(run: (requests: Array<{ url: string; file: File; form: FormData }>) => Promise<void>): Promise<void> {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; file: File; form: FormData }> = [];
  globalThis.fetch = async (input, init) => {
    assert.ok(init?.body instanceof FormData);
    const file = init.body.get("file");
    assert.ok(file instanceof File);
    requests.push({ url: String(input), file, form: init.body });
    return Response.json(String(input).includes("profile-image") ? { status: "ok", url: "test" } : { embed_id: "test" });
  };
  try {
    await run(requests);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function pngWithText(): Uint8Array {
  const original = readFileSync(new URL("../../../apps/web_app/tests/fixtures/sample.png", import.meta.url));
  // The PNG parser removes ancillary tEXt chunks. CRC is valid so the fixture
  // remains a normal image for upload processing.
  const payload = Buffer.from("Author\0private-location-token");
  const type = Buffer.from("tEXt");
  const crcInput = Buffer.concat([type, payload]);
  let crc = 0xffffffff;
  for (const byte of crcInput) {
    crc ^= byte;
    for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  const chunk = Buffer.alloc(12 + payload.length);
  chunk.writeUInt32BE(payload.length, 0);
  type.copy(chunk, 4);
  payload.copy(chunk, 8);
  chunk.writeUInt32BE((crc ^ 0xffffffff) >>> 0, 8 + payload.length);
  const firstChunkEnd = 8 + 12 + original.readUInt32BE(8);
  return Buffer.concat([original.subarray(0, firstChunkEnd), chunk, original.subarray(firstChunkEnd)]);
}

function wavWithInfo(): Uint8Array {
  const info = Buffer.from("private-recorder-token\0");
  const inam = Buffer.alloc(8 + info.length + (info.length & 1));
  inam.write("INAM", 0);
  inam.writeUInt32LE(info.length, 4);
  info.copy(inam, 8);
  const list = Buffer.alloc(12 + inam.length);
  list.write("LIST", 0);
  list.writeUInt32LE(4 + inam.length, 4);
  list.write("INFO", 8);
  inam.copy(list, 12);
  const fmt = Buffer.from([0x66,0x6d,0x74,0x20,16,0,0,0,1,0,1,0,0x40,0x1f,0,0,0x80,0x3e,0,0,2,0,16,0]);
  const data = Buffer.from([0x64,0x61,0x74,0x61,4,0,0,0,0,0,0,0]);
  const riff = Buffer.alloc(12);
  riff.write("RIFF", 0);
  riff.writeUInt32LE(4 + fmt.length + list.length + data.length, 4);
  riff.write("WAVE", 8);
  return Buffer.concat([riff, fmt, list, data]);
}

// contract-test: direct surface=cli assertions=pii.surface.semantic-parity
it("uploads sanitized image, PDF, audio, and Office bytes with their original filenames", async () => {
  const pdf = await PDFDocument.create();
  pdf.addPage([100, 100]);
  pdf.setTitle("private-document-title");
  const docx = new JSZip();
  docx.file("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>');
  docx.file("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Visible text</w:t></w:r></w:p></w:body></w:document>');
  docx.file("docProps/core.xml", '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"><dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">private-office-author</dc:creator></cp:coreProperties>');
  const fixtures = [
    { name: "private-image.png", bytes: pngWithText(), marker: "private-location-token", mime: "image/png" },
    { name: "private-document.pdf", bytes: await pdf.save(), marker: "private-document-title", mime: "application/pdf" },
    { name: "private-audio.wav", bytes: wavWithInfo(), marker: "private-recorder-token", mime: "audio/wav" },
    { name: "private-office.docx", bytes: await docx.generateAsync({ type: "uint8array" }), marker: "private-office-author", mime: "application/octet-stream" },
  ];
  await interceptUpload(async (requests) => {
    for (const fixture of fixtures) {
      await withUploadFile(fixture.name, fixture.bytes, async (path) => {
        await uploadFile(path, session);
        const request = requests.at(-1)!;
        assert.equal(request.file.name, fixture.name);
        assert.equal(request.file.type, fixture.mime);
        const uploaded = Buffer.from(await request.file.arrayBuffer());
        assert.ok(uploaded.byteLength > 0);
        if (fixture.name.endsWith(".pdf")) {
          const cleaned = await PDFDocument.load(uploaded);
          assert.notEqual(cleaned.getTitle(), fixture.marker);
        } else if (fixture.name.endsWith(".docx")) {
          const cleaned = await JSZip.loadAsync(uploaded);
          const core = await cleaned.file("docProps/core.xml")?.async("string");
          assert.ok(core);
          assert.equal(core.includes(fixture.marker), false);
          assert.ok(cleaned.file("word/document.xml"));
        } else {
          assert.equal(uploaded.includes(fixture.marker), false, fixture.name);
        }
      });
    }
  });
});

// contract-test: direct surface=cli assertions=pii.surface.semantic-parity
it("sanitizes personal and team avatar POST bytes", async () => {
  await interceptUpload(async (requests) => {
    await withUploadFile("private-avatar.png", pngWithText(), async (path) => {
      await uploadProfileImage(path, session);
      await uploadTeamProfileImage(path, session, "team-1", "encrypted-metadata");
    });
    assert.equal(requests.length, 2);
    for (const request of requests) {
      assert.equal(request.file.name, "private-avatar.png");
      assert.equal(Buffer.from(await request.file.arrayBuffer()).includes("private-location-token"), false);
    }
    assert.equal(requests[1]?.form.get("team_id"), "team-1");
    assert.equal(requests[1]?.form.get("encrypted_profile_image_metadata"), "encrypted-metadata");
  });
});

// contract-test: direct surface=cli assertions=pii.surface.semantic-parity
it("re-encodes a supported TIFF as metadata-free PNG before upload", async () => {
  const tiff = await sharp({ create: { width: 2, height: 2, channels: 3, background: "red" } }).tiff().toBuffer();
  await interceptUpload(async (requests) => {
    await withUploadFile("private-scan.tiff", tiff, async (path) => {
      await uploadFile(path, session);
    });
    assert.equal(requests[0]?.file.name, "private-scan.tiff");
    assert.equal(requests[0]?.file.type, "image/png");
    const bytes = Buffer.from(await requests[0]!.file.arrayBuffer());
    assert.equal((await sharp(bytes).metadata()).format, "png");
  });
});

// contract-test: direct surface=cli assertions=pii.surface.semantic-parity
it("preserves upload success and bytes when cleanup fails, without logging private details", async () => {
  const invalid = Buffer.from("private-failed-cleanup-token");
  const originalError = console.error;
  const warnings: string[] = [];
  console.error = (...args) => { warnings.push(args.map(String).join(" ")); };
  try {
    await interceptUpload(async (requests) => {
      await withUploadFile("private-person.png", invalid, async (path) => {
        await uploadFile(path, session);
      });
      assert.equal(requests[0]?.file.name, "private-person.png");
      assert.deepEqual(Buffer.from(await requests[0]!.file.arrayBuffer()), invalid);
    });
  } finally {
    console.error = originalError;
  }
  assert.equal(warnings.length, 1);
  assert.match(warnings[0]!, /could not remove embedded file metadata/i);
  assert.equal(warnings[0]!.includes("private"), false);
});
