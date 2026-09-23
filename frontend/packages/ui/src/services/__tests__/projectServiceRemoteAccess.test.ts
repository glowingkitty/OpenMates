/** Browser Project remote-access transport contract tests. */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";

vi.mock("../../config/api", () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));

import { decryptWithEmbedKey, encryptWithEmbedKey, wrapEmbedKeyWithChatKey } from "../cryptoService";
import {
  activateProjectFocus,
  approveProjectWrite,
  deactivateProjectFocus,
  getActiveProjectFocus,
  getProjectSettings,
  getProjectFileRevisionReceipt,
  PROJECT_BROWSER_REMOTE_READ_MAX_BYTES,
  PROJECT_BROWSER_REMOTE_READ_MAX_LINES,
  readEncryptedProjectFile,
  requestProjectRemoteAccess,
  type ProjectSourceViewModel,
  type ProjectViewModel,
} from "../projectService";

Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });

const projectKey = new Uint8Array(32).fill(7);
const project = {
  project_id: "project-1",
  name: "Project",
  description: "",
  projectKey,
  encrypted: { project_id: "project-1", encrypted_project_key: "wrapped", encrypted_name: "cipher", created_at: 1, updated_at: 1, last_opened_at: 1 },
} satisfies ProjectViewModel;
const source = {
  source_id: "source-1",
  source_type: "local_git_repository",
  displayName: "repo",
  metadata: {},
  capabilities: ["read"],
  status: "connected",
  sourceSessionId: null,
  keyEpoch: null,
  encrypted: {
    source_id: "source-1", source_type: "local_git_repository", encrypted_display_name: "cipher",
    encrypted_metadata: "cipher", capabilities: ["read"], status: "connected", created_at: 1, updated_at: 1,
  },
} satisfies ProjectSourceViewModel;

describe("Project browser remote-access transport", () => {
  beforeEach(() => vi.restoreAllMocks());

  // contract-test: direct surface=gui.web assertions=projects.files.write-policy-setup,projects.focus.default-owned,projects.files.no-server-decryption-authority
  it("initializes legacy Project settings with the apply-and-show default and encrypted focus", async () => {
    const calls: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {};
      calls.push({ url, method, body });
      if (method === "GET") {
        return Response.json({ settings: {
          write_mode: "apply_and_show", selection_required: false,
          default_focus_id_hash: null, encrypted_settings: null, updated_at: null,
        } });
      }
      return Response.json({ settings: {
        write_mode: body.write_mode, selection_required: false,
        default_focus_id_hash: "focus-hash", encrypted_settings: body.encrypted_settings, updated_at: body.updated_at,
      } });
    });

    const settings = await getProjectSettings(project, { teamId: "team-1" });

    expect(settings.writeMode).toBe("apply_and_show");
    expect(settings.settings.default_focus).toMatchObject({ name: "Work on Project", source: "generated" });
    expect(calls).toHaveLength(2);
    expect(calls[1]?.url).toContain("team_id=team-1");
    expect(calls[1]?.method).toBe("PATCH");
    expect(calls[1]?.body).toMatchObject({ write_mode: "apply_and_show" });
    expect(String(calls[1]?.body.encrypted_settings)).not.toContain("Work on Project");
  });

  // contract-test: direct surface=gui.web assertions=projects.access.explicit-context,projects.keys.client-wrapped,projects.files.no-server-decryption-authority
  it("binds Team routing, v2 identity, and conservative read limits before a cancellable poll", async () => {
    expect(PROJECT_BROWSER_REMOTE_READ_MAX_BYTES).toBe(180 * 1024);
    const controller = new AbortController();
    const browserContext = { ownerId: "user-1", teamId: "team-1" };
    const discoveryNonce = { value: "" };
    let postCount = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      expect(url).toContain("team_id=team-1");
      if (init?.method === "POST") {
        postCount += 1;
        const body = JSON.parse(String(init.body)) as { encrypted_envelope: string };
        const plaintext = await decryptWithEmbedKey(body.encrypted_envelope, projectKey);
        const payload = JSON.parse(plaintext ?? "{}") as Record<string, unknown>;
        if (postCount === 1) {
          browserContext.teamId = "team-2";
          discoveryNonce.value = String(payload.nonce);
          return new Response(JSON.stringify({
            request_id: "discovery-request",
            status: "delivered",
            source_session_id: "team-session",
            key_epoch: 2,
            routing_identity: {
              context_type: "team",
              context_id_hash: "team-hash",
              host_member_hash: "host-member",
              host_device_fingerprint_hash: "host-device",
              requester_member_hash: "requester-member",
              requester_device_fingerprint_hash: "requester-device",
            },
          }), { status: 202 });
        }
        const args = payload.arguments as Record<string, unknown>;
        expect(payload.operation).toBe("read_text");
        expect(args.max_bytes).toBe(PROJECT_BROWSER_REMOTE_READ_MAX_BYTES);
        expect(args.max_lines).toBe(PROJECT_BROWSER_REMOTE_READ_MAX_LINES);
        return new Response(JSON.stringify({ request_id: "read-request", status: "delivered" }), { status: 202 });
      }
      if (postCount === 1) {
        return new Response(JSON.stringify({
          encrypted_envelope: await encryptWithEmbedKey(JSON.stringify({
            type: "routing_discovery_result",
            nonce: discoveryNonce.value,
          }), projectKey),
        }), { status: 200 });
      }
      controller.abort();
      return new Response("backend private diagnostic", { status: 404 });
    });

    await expect(requestProjectRemoteAccess(
      project, source, browserContext, "read_text", { path: "large-demo.ts" }, controller.signal,
    )).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  // contract-test: direct surface=gui.web assertions=projects.access.explicit-context,projects.files.no-server-decryption-authority
  it("does not expose raw backend response bodies", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      expect(String(input)).not.toContain("team_id=");
      return new Response("secret backend body", { status: 500 });
    });
    const personalSource = { ...source, sourceSessionId: "session-1", keyEpoch: 1 };

    await expect(requestProjectRemoteAccess(
      project, personalSource, { ownerId: "user-1" }, "list", { path: "." },
    )).rejects.toThrow("The Project source request failed");
    await expect(requestProjectRemoteAccess(
      project, personalSource, { ownerId: "user-1" }, "list", { path: "." },
    )).rejects.not.toThrow("secret backend body");
    await expect(requestProjectRemoteAccess(
      project, personalSource, { ownerId: "user-1" }, "list", { path: "." },
    )).rejects.toMatchObject({ code: "operation_failed" });
  });

  // contract-test: supporting surface=gui.web assertions=projects.access.explicit-context,projects.files.no-server-decryption-authority
  it("removes the abort listener after a completed poll delay", async () => {
    const controller = new AbortController();
    const removeListener = vi.spyOn(controller.signal, "removeEventListener");
    let getCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "POST") {
        return new Response(JSON.stringify({ request_id: "request-1", status: "delivered" }), { status: 202 });
      }
      getCount += 1;
      return new Response("", { status: getCount === 1 ? 404 : 500 });
    });
    const personalSource = { ...source, sourceSessionId: "session-1", keyEpoch: 1 };

    await expect(requestProjectRemoteAccess(
      project, personalSource, { ownerId: "user-1" }, "list", { path: "." }, controller.signal,
    )).rejects.toThrow("The Project source request failed");
    expect(removeListener).toHaveBeenCalledWith("abort", expect.any(Function));
  });

  // contract-test: direct surface=gui.web assertions=projects.files.write-policy-enforcement,projects.files.chat-focus-required,projects.access.explicit-context
  it("exposes focus, write approval, and receipt APIs with explicit Team context", async () => {
    const calls: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {};
      calls.push({ url, method, body });
      if (url.includes("focus/activate")) return Response.json({ focus: { active: true, project_id: "project-1", focus_id: "focus-1", team_id: "team-1", activated_at: 1 } });
      if (url.includes("focus/current")) return Response.json({ focus: { active: true, project_id: "project-1", focus_id: "focus-1", team_id: "team-1", activated_at: 1 } });
      if (url.includes("write-approvals")) return Response.json({ approval: { approved: true, operation_id: "op-1", proposal_digest: "a".repeat(64), approved_at: 2 } });
      if (url.includes("revision-receipts")) return new Response("", { status: 404 });
      return Response.json({ deactivated: true });
    });

    await activateProjectFocus("project-1", { chat_id: "chat-1", focus_id: "focus-1", instruction: "Work" }, { teamId: "team-1" });
    expect((await getActiveProjectFocus("chat-1"))?.project_id).toBe("project-1");
    expect((await approveProjectWrite("project-1", { chat_id: "chat-1", operation_id: "op-1", proposal_digest: "a".repeat(64) }, { teamId: "team-1" })).approved).toBe(true);
    await deactivateProjectFocus("chat-1");
    await expect(getProjectFileRevisionReceipt("project-1", "embed-1", "op-1", "chat-1", "a".repeat(64), { teamId: "team-1" })).resolves.toBeNull();
    expect(calls[0]?.url).toContain("team_id=team-1");
    expect(calls[0]?.body).toEqual({ chat_id: "chat-1", focus_id: "focus-1", instruction: "Work" });
    expect(calls[2]?.url).toContain("team_id=team-1");
    expect(calls[4]?.url).toContain("proposal_digest=");
  });

  // contract-test: direct surface=gui.web assertions=projects.files.hosted-ciphertext-commit,projects.files.no-server-decryption-authority
  it("decrypts a hosted Project file head only in the browser", async () => {
    const embedKey = new Uint8Array(32).fill(9);
    const wrapped = await wrapEmbedKeyWithChatKey(embedKey, projectKey);
    const encrypted = await encryptWithEmbedKey(JSON.stringify({ code: "private source\n" }), embedKey);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({
      embed: { embed_id: "embed-1", encrypted_content: encrypted, version_number: 3 },
      embed_keys: [{ key_type: "project", encrypted_embed_key: wrapped }],
      has_initial_history: true,
    }));

    const head = await readEncryptedProjectFile(project, "embed-1", { teamId: "team-1" });
    expect(head.content).toEqual({ code: "private source\n" });
    expect(head.revision).toBe(3);
    expect(head.hasInitialHistory).toBe(true);
    expect(String(vi.mocked(fetch).mock.calls[0]?.[0])).toContain("team_id=team-1");
  });

  // contract-test: direct surface=gui.web assertions=projects.files.no-server-decryption-authority,projects.files.write-policy-enforcement,projects.files.ignored-exact-inclusion
  it("keeps remote mutations and ignored-read grants inside the encrypted transport", async () => {
    const personalSource = { ...source, sourceSessionId: "session-1", keyEpoch: 1 };
    const controller = new AbortController();
    const posts: Array<Record<string, unknown>> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        posts.push(body);
        const plaintext = await decryptWithEmbedKey(String(body.encrypted_envelope), projectKey);
        const envelope = JSON.parse(plaintext ?? "{}") as Record<string, unknown>;
        expect(JSON.stringify(body)).not.toContain("private source");
        if (body.operation === "create_file") {
          expect(body.chat_id).toBe("chat-1");
          expect(body.operation_id).toBe("op-create");
          expect(body.proposal_digest).toMatch(/^[a-f0-9]{64}$/);
          expect((envelope.arguments as Record<string, unknown>).mutation).toMatchObject({ path: "src/new.ts", content: "private source" });
        } else {
          expect(envelope.ignored_read_grant).toMatchObject({ path: "ignored.log", requestId: body.request_id });
          expect(envelope.ignored_read_context).toEqual({ chatId: "chat-1", operationId: "op-read" });
        }
        return Response.json({ request_id: body.request_id, status: "delivered" }, { status: 202 });
      }
      controller.abort();
      return new Response("", { status: 404 });
    });

    await expect(requestProjectRemoteAccess(project, personalSource, { ownerId: "user-1" }, "create_file", {
      chat_id: "chat-1",
      mutation: { operation: "create_file", operation_id: "op-create", path: "src/new.ts", expected_base: null, content: "private source" },
    }, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    const second = new AbortController();
    controller.signal.onabort = () => undefined;
    vi.mocked(fetch).mockImplementationOnce(async (_input, init) => {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      posts.push(body);
      const plaintext = await decryptWithEmbedKey(String(body.encrypted_envelope), projectKey);
      const envelope = JSON.parse(plaintext ?? "{}") as Record<string, unknown>;
      expect(envelope.ignored_read_grant).toMatchObject({ path: "ignored.log", requestId: body.request_id });
      expect(envelope.ignored_read_context).toEqual({ chatId: "chat-1", operationId: "op-read" });
      return Response.json({ request_id: body.request_id, status: "delivered" }, { status: 202 });
    }).mockImplementationOnce(async () => { second.abort(); return new Response("", { status: 404 }); });
    await expect(requestProjectRemoteAccess(project, personalSource, { ownerId: "user-1" }, "read_text", { path: "ignored.log" }, second.signal, {
      path: "ignored.log", chatId: "chat-1", operationId: "op-read",
    })).rejects.toMatchObject({ name: "AbortError" });
    expect(posts).toHaveLength(2);
  });
});
