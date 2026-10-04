import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { OpenMatesWsClient } from "../src/ws.ts";

const require = createRequire(import.meta.url);
const { WebSocketServer } = require("ws") as typeof import("ws");

describe("CLI recovery output discovery", () => {
  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover,chats.sync.key-gated-recovery
  it("keeps more than one bounded discovery frame in order until the completion fence", async () => {
    const server = new WebSocketServer({ port: 0 });
    await new Promise<void>((resolve) => server.once("listening", resolve));
    const address = server.address();
    assert.ok(address && typeof address !== "string");
    const output = (index: number) => ({
      record_id: `record-${index}`, root_chat_id: "root", target_chat_id: "child",
      turn_id: "turn", subject_id: `subject-${index}`, output_kind: "message",
      output_version: index + 1, chat_key_version: 1,
    });
    let advertisedCapabilities = "";
    server.on("connection", (socket, request) => {
      advertisedCapabilities = new URL(request.url ?? "/", "http://localhost")
        .searchParams.get("client_capabilities") ?? "";
      socket.send(JSON.stringify({ type: "recovery_outputs_available", payload: {
        outputs: Array.from({ length: 70 }, (_, index) => output(index)),
      } }));
      socket.send(JSON.stringify({ type: "recovery_outputs_available", payload: {
        outputs: Array.from({ length: 70 }, (_, index) => output(index + 70)),
      } }));
      socket.send(JSON.stringify({ type: "recovery_outputs_discovery_complete", payload: { status: "completed" } }));
    });
    const client = new OpenMatesWsClient({
      apiUrl: `http://127.0.0.1:${address.port}`, sessionId: "session", wsToken: "token", refreshToken: null,
    });
    try {
      await client.open();
      await client.waitForRecoveryOutputDiscovery();
      const pages = client.drainAvailableRecoveryOutputPages();
      assert.deepEqual(pages.map((page) => page.length), [70, 70]);
      assert.equal(pages[0][0].record_id, "record-0");
      assert.equal(pages[1][69].record_id, "record-139");
      assert.deepEqual(client.drainAvailableRecoveryOutputPages(), []);
      assert.ok(advertisedCapabilities.split(",").includes("canonical_embed_receipts_v1"));
      assert.ok(advertisedCapabilities.split(",").includes("typed_recovery_outputs_v2"));
    } finally {
      client.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: direct surface=cli assertions=chats.completion.recovery-takeover
  it("rejects a failed discovery fence before claiming an empty snapshot", async () => {
    const server = new WebSocketServer({ port: 0 });
    await new Promise<void>((resolve) => server.once("listening", resolve));
    const address = server.address();
    assert.ok(address && typeof address !== "string");
    server.on("connection", (socket) => socket.send(JSON.stringify({
      type: "recovery_outputs_discovery_complete", payload: { status: "failed" },
    })));
    const client = new OpenMatesWsClient({
      apiUrl: `http://127.0.0.1:${address.port}`, sessionId: "session", wsToken: "token", refreshToken: null,
    });
    try {
      await client.open();
      await assert.rejects(client.waitForRecoveryOutputDiscovery(), /did not complete/);
    } finally {
      client.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=chats.sync.key-gated-recovery,chats.completion.recovery-takeover
  it("retains bounded reconnect discovery until the CLI has synced its root key", async () => {
    const server = new WebSocketServer({ port: 0 });
    await new Promise<void>((resolve) => server.once("listening", resolve));
    const address = server.address();
    assert.ok(address && typeof address !== "string");
    const root = "22222222-2222-4222-8222-222222222222";
    const otherRoot = "33333333-3333-4333-8333-333333333333";
    const output = (id: string, rootId: string) => ({
      record_id: id, root_chat_id: rootId,
      target_chat_id: "99999999-9999-4999-8999-999999999999",
      turn_id: "44444444-4444-4444-8444-444444444444",
      subject_id: "child-output-1", output_kind: "message",
      output_version: 1, chat_key_version: 7,
    });
    server.on("connection", (socket) => {
      socket.send(JSON.stringify({ type: "recovery_outputs_available", payload: {
        outputs: [output("a", root), output("a", root),
          { ...output("b", otherRoot), root_hashed_team_id: "a".repeat(64) },
          { ...output("c", otherRoot), output_kind: "embed", message_role: null }],
      } }));
    });
    const client = new OpenMatesWsClient({
      apiUrl: `http://127.0.0.1:${address.port}`, sessionId: "session", wsToken: "token", refreshToken: null,
    });
    try {
      await client.open();
      await new Promise((resolve) => setTimeout(resolve, 20));
      assert.deepEqual(client.drainAvailableRecoveryOutputs(root).map((item) => item.record_id), ["a"]);
      const remaining = client.drainAvailableRecoveryOutputs();
      assert.deepEqual(remaining.map((item) => item.record_id), ["b", "c"]);
      assert.equal(remaining[0].root_hashed_team_id, "a".repeat(64));
    } finally {
      client.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  // contract-test: supporting surface=cli assertions=chats.sync.key-gated-recovery,chats.completion.recovery-takeover
  it("fails closed when recovery discovery has an invalid output identity", async () => {
    const server = new WebSocketServer({ port: 0 });
    await new Promise<void>((resolve) => server.once("listening", resolve));
    const address = server.address();
    assert.ok(address && typeof address !== "string");
    server.on("connection", (socket) => socket.send(JSON.stringify({
      type: "recovery_outputs_available", payload: { outputs: [{
        record_id: "bad", root_chat_id: "root", target_chat_id: "child", turn_id: "turn",
        subject_id: "subject", output_kind: "message", output_version: 1,
        chat_key_version: 1, root_hashed_team_id: "wrong-team-hash",
      }] },
    })));
    const client = new OpenMatesWsClient({
      apiUrl: `http://127.0.0.1:${address.port}`, sessionId: "session", wsToken: "token", refreshToken: null,
    });
    try {
      await client.open();
      await new Promise((resolve) => setTimeout(resolve, 20));
      assert.throws(() => client.drainAvailableRecoveryOutputs(), /invalid identity/);
    } finally {
      client.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});
