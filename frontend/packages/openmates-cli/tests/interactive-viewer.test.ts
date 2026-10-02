// contract-test-file: infrastructure
import { it } from "node:test";
import assert from "node:assert/strict";
import { OpenMatesClient } from "../src/client.ts";

// contract-test: supporting surface=cli assertions=notifications.delivery.email-enabled
it("keeps the TTY viewer after a request and closes it on chat switch and exit", async () => {
  const inputDescriptor = Object.getOwnPropertyDescriptor(process.stdin, "isTTY");
  const outputDescriptor = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");
  Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
  Object.defineProperty(process.stdout, "isTTY", { configurable: true, value: true });
  try {
    const client = Object.create(OpenMatesClient.prototype) as OpenMatesClient;
    const sockets: Array<{ sent: Array<[string, unknown]>; closed: boolean; close: () => void; send: (type: string, payload: unknown) => void; onClose: (callback: () => void) => void }> = [];
    (client as any).hasSession = () => true;
    (client as any).openWsClient = async () => {
      const socket = {
        sent: [] as Array<[string, unknown]>, closed: false,
        close() { this.closed = true; },
        send(type: string, payload: unknown) { this.sent.push([type, payload]); },
        onClose(_callback: () => void) {},
      };
      sockets.push(socket);
      return { ws: socket };
    };

    client.beginInteractiveViewerSession();
    await client.setInteractiveChatViewer("chat-a");
    assert.equal(sockets.length, 1);
    assert.deepEqual(sockets[0].sent, [["set_active_chat", { chat_id: "chat-a" }]]);
    await client.setInteractiveChatViewer("chat-a");
    assert.equal(sockets.length, 1, "request completion must leave the viewer open");
    assert.equal(sockets[0].closed, false);

    await client.setInteractiveChatViewer("chat-b");
    assert.equal(sockets[0].closed, true);
    assert.deepEqual(sockets[1].sent, [["set_active_chat", { chat_id: "chat-b" }]]);
    client.endInteractiveViewerSession();
    assert.equal(sockets[1].closed, true);
    await client.setInteractiveChatViewer("chat-c");
    assert.equal(sockets.length, 2, "finished TUI cannot reopen viewer after a late response");
  } finally {
    if (inputDescriptor) Object.defineProperty(process.stdin, "isTTY", inputDescriptor);
    else delete (process.stdin as { isTTY?: boolean }).isTTY;
    if (outputDescriptor) Object.defineProperty(process.stdout, "isTTY", outputDescriptor);
    else delete (process.stdout as { isTTY?: boolean }).isTTY;
  }
});
