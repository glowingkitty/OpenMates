// contract-test-file: infrastructure
/** Synthetic WebSocket coverage for terminal AI cancellation; no product server or account. */
import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { createRequire } from "node:module";
import { OpenMatesClient } from "../src/client.ts";
import { OpenMatesWsClient, WebSocketProtocolError, type StreamEvent } from "../src/ws.ts";

const require = createRequire(import.meta.url);
const { WebSocketServer } = require("ws");
type ServerSocket = { on: (name: string, handler: (data: Buffer) => void) => void; send: (data: string) => void };

async function withServer(run: (apiUrl: string, server: InstanceType<typeof WebSocketServer>) => Promise<void>): Promise<void> {
  const server = new WebSocketServer({ port: 0 });
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await run(`http://127.0.0.1:${address.port}`, server);
  } finally {
    for (const socket of server.clients) socket.terminate();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

function clientUsingSyntheticSocket(apiUrl: string): OpenMatesClient {
  const client = new OpenMatesClient({ apiUrl, session: { apiUrl, sessionId: "fixture", cookies: {} } as never });
  (client as unknown as { openWsClient: () => Promise<{ ws: OpenMatesWsClient }> }).openWsClient = async () => {
    const ws = new OpenMatesWsClient({ apiUrl, sessionId: "fixture", wsToken: "fixture", refreshToken: null });
    await ws.open();
    return { ws };
  };
  return client;
}

test("typing and later stream events retain the server AI task ID", async () => {
  await withServer(async (apiUrl, server) => {
    server.once("connection", (socket: ServerSocket) => {
      const send = (type: string, payload: Record<string, unknown>) => socket.send(JSON.stringify({ type, payload }));
      setTimeout(() => {
        send("ai_typing_started", { chat_id: "chat-1", task_id: "task-1", category: "general_knowledge" });
        send("ai_message_update", { chat_id: "chat-1", user_message_id: "user-1", full_content_so_far: "Hello", is_final_chunk: false });
        send("ai_message_update", { chat_id: "chat-1", user_message_id: "user-1", full_content_so_far: "Hello.", is_final_chunk: true });
        send("post_processing_completed", { chat_id: "chat-1" });
      }, 5);
    });
    const ws = new OpenMatesWsClient({ apiUrl, sessionId: "fixture", wsToken: "fixture", refreshToken: null });
    try {
      await ws.open();
      const events: StreamEvent[] = [];
      await ws.collectAiResponse("user-1", "chat-1", { timeoutMs: 1_000, onStream: (event) => events.push(event) });
      assert.deepEqual(events.map((event) => [event.kind, event.taskId]), [
        ["typing", "task-1"], ["chunk", "task-1"], ["done", "task-1"],
      ]);
    } finally { ws.close(); }
  });
});

test("cancelAITask sends both IDs, ignores unrelated receipt, and returns server acknowledgement", async () => {
  await withServer(async (apiUrl, server) => {
    server.once("connection", (socket: ServerSocket) => socket.on("message", (raw) => {
      const frame = JSON.parse(raw.toString()) as { type: string; payload: Record<string, unknown> };
      assert.deepEqual(frame, { type: "cancel_ai_task", payload: { task_id: "task-1", chat_id: "chat-1" } });
      socket.send(JSON.stringify({ type: "ai_task_cancel_requested", payload: { task_id: "other", status: "revocation_sent" } }));
      socket.send(JSON.stringify({ type: "ai_task_cancel_requested", payload: { task_id: "task-1", status: "revocation_sent" } }));
    }));
    assert.deepEqual(await clientUsingSyntheticSocket(apiUrl).cancelAITask("task-1", "chat-1"), {
      taskId: "task-1", status: "revocation_sent",
    });
  });
});

test("cancelAITask surfaces a server failure instead of reporting success", async () => {
  await withServer(async (apiUrl, server) => {
    server.once("connection", (socket: ServerSocket) => socket.on("message", () => {
      socket.send(JSON.stringify({ type: "error", payload: { message: "Cancellation failed", details: "synthetic" } }));
    }));
    await assert.rejects(clientUsingSyntheticSocket(apiUrl).cancelAITask("task-1", "chat-1"),
      (error: unknown) => error instanceof WebSocketProtocolError && error.message === "Cancellation failed");
  });
});
