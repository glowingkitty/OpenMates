/**
 * Project README upload integration contract.
 * A normal root README upload must keep its Markdown in the client-encrypted
 * code embed so Overview can read it without server-side plaintext access.
 */

import { webcrypto } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../config/api", () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock("../cryptoService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../cryptoService")>()),
  wrapEmbedKeyWithMasterKey: vi.fn(async () => "owner-wrapped-key"),
}));
vi.mock("../embedStore", () => ({
  embedStore: { put: vi.fn(async () => undefined), registerEmbedRef: vi.fn() },
}));
vi.mock("../../components/enter_message/services/uploadService", () => ({
  uploadFileToServer: vi.fn(async () => { throw new Error("Generic upload must not run for README.md"); }),
}));

import { decryptWithEmbedKey, unwrapEmbedKeyWithChatKey } from "../cryptoService";
import { uploadFileToServer } from "../../components/enter_message/services/uploadService";
import type { UploadFileResponse } from "../../components/enter_message/services/uploadService";
import { uploadFileToProject, type ProjectViewModel } from "../projectService";

Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });

const projectKey = new Uint8Array(32).fill(17);
const project = {
  project_id: "readme-upload-project",
  name: "README upload",
  description: "",
  icon: "folder",
  projectKey,
  encrypted: {
    project_id: "readme-upload-project",
    encrypted_project_key: "wrapped",
    encrypted_name: "ciphertext",
    created_at: 1,
    updated_at: 1,
    last_opened_at: 1,
  },
} satisfies ProjectViewModel;

describe("Project root README upload", () => {
  beforeEach(() => vi.restoreAllMocks());

  // contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity,projects.files.no-server-decryption-authority
  it("stores normal README.md text in an encrypted inline embed that Overview can read", async () => {
    const source = "# Project roadmap\n\n- Ship the overview\n";
    let body: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      expect(String(input)).toContain("/v1/projects/readme-upload-project/upload-embed");
      expect(init?.method).toBe("POST");
      body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return Response.json({});
    });

    await uploadFileToProject(project, new File([source], "README.md", { type: "text/markdown" }));

    expect(uploadFileToServer).not.toHaveBeenCalled();
    expect(body).not.toBeNull();
    const upload = body as {
      embed: { encrypted_content: string; encrypted_type: string };
      embed_keys: Array<{ key_type: string; encrypted_embed_key: string }>;
      item: { folder_id: string | null; encrypted_display_name: string; encrypted_metadata: string };
    };
    expect(upload.item.folder_id).toBeNull();
    expect(JSON.stringify(upload)).not.toContain(source);
    const projectWrap = upload.embed_keys.find((key) => key.key_type === "project");
    expect(projectWrap).toBeDefined();
    const embedKey = await unwrapEmbedKeyWithChatKey(projectWrap!.encrypted_embed_key, projectKey);
    expect(embedKey).not.toBeNull();
    const content = await decryptWithEmbedKey(upload.embed.encrypted_content, embedKey!);
    expect(JSON.parse(content ?? "{}" )).toMatchObject({ code: source, filename: "README.md", language: "markdown" });
    expect(await decryptWithEmbedKey(upload.item.encrypted_display_name, projectKey)).toBe("README.md");
    const metadata = JSON.parse((await decryptWithEmbedKey(upload.item.encrypted_metadata, projectKey)) ?? "{}");
    expect(metadata.readme_uploaded_at_ms).toEqual(expect.any(Number));
  });

  // contract-test: supporting surface=gui.web assertions=projects.uploads.project-wrapped,projects.surface.semantic-parity
  it("places uploaded files in the selected folder without persisting folder ids in metadata", async () => {
    const uploadedFile = {
      embed_id: "file-embed-1",
      filename: "diagram.png",
      content_type: "image/png",
      content_hash: "content-hash",
      files: {},
      s3_base_url: "https://files.example.test",
      aes_key: "encrypted-file-key",
      aes_nonce: "nonce",
      vault_wrapped_aes_key: "vault-key",
      malware_scan: "clean",
      ai_detection: null,
      deduplicated: false,
    } satisfies UploadFileResponse;
    vi.mocked(uploadFileToServer).mockResolvedValueOnce(uploadedFile);
    const bodies: Array<Record<string, unknown>> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return Response.json({});
    });

    await uploadFileToProject(project, new File(["image"], "diagram.png", { type: "image/png" }), {}, { folderId: "folder-1" });
    await uploadFileToProject(project, new File(["# Nested"], "README.md", { type: "text/markdown" }), {}, { folderId: "folder-1" });
    const mindMap = JSON.stringify({
      openmatesType: "mindmap", schemaVersion: 1, title: "Plan", rootId: "root",
      nodes: [{ id: "root", label: "Plan" }],
    });
    await uploadFileToProject(project, new File([mindMap], "plan.ommindmap", { type: "application/json" }), {}, { folderId: "folder-1" });

    expect(bodies).toHaveLength(3);
    for (const body of bodies) {
      const savedItem = body.item as { folder_id: string; encrypted_metadata: string };
      expect(savedItem.folder_id).toBe("folder-1");
      const metadata = await decryptWithEmbedKey(savedItem.encrypted_metadata, projectKey);
      expect(metadata).not.toContain("folder-1");
    }
  });
});
