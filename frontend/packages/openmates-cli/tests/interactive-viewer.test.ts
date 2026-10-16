// contract-test-file: infrastructure
import { it } from "node:test";
import assert from "node:assert/strict";
import { OpenMatesClient } from "../src/client.ts";

async function withTty(action: () => Promise<void>): Promise<void> {
  const inputDescriptor = Object.getOwnPropertyDescriptor(process.stdin, "isTTY");
  const outputDescriptor = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");
  Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
  Object.defineProperty(process.stdout, "isTTY", { configurable: true, value: true });
  try {
    await action();
  } finally {
    if (inputDescriptor) Object.defineProperty(process.stdin, "isTTY", inputDescriptor);
    else delete (process.stdin as { isTTY?: boolean }).isTTY;
    if (outputDescriptor) Object.defineProperty(process.stdout, "isTTY", outputDescriptor);
    else delete (process.stdout as { isTTY?: boolean }).isTTY;
  }
}

// contract-test: supporting surface=cli assertions=notifications.delivery.email-enabled
it("keeps the TTY viewer after a request and closes it on chat switch and exit", async () => {
  await withTty(async () => {
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
  });
});

// contract-test: supporting surface=cli assertions=notifications.delivery.email-enabled
it("closes an earlier pending viewer when the same chat opens again", async () => {
  await withTty(async () => {
    const client = Object.create(OpenMatesClient.prototype) as OpenMatesClient;
    const sockets: Array<{ sent: Array<[string, unknown]>; closed: boolean; close: () => void; send: (type: string, payload: unknown) => void; onClose: (callback: () => void) => void }> = [];
    const pending: Array<(value: { ws: typeof sockets[number] }) => void> = [];
    (client as any).hasSession = () => true;
    (client as any).openWsClient = () => new Promise<{ ws: typeof sockets[number] }>((resolve) => {
      const socket = {
        sent: [] as Array<[string, unknown]>, closed: false,
        close() { this.closed = true; },
        send(type: string, payload: unknown) { this.sent.push([type, payload]); },
        onClose(_callback: () => void) {},
      };
      sockets.push(socket);
      pending.push(resolve);
    });

    client.beginInteractiveViewerSession();
    const first = client.setInteractiveChatViewer("chat-a");
    const second = client.setInteractiveChatViewer("chat-a");
    assert.equal(pending.length, 2);
    pending[1]({ ws: sockets[1] });
    await second;
    pending[0]({ ws: sockets[0] });
    await first;
    assert.equal(sockets[0].closed, true, "superseded open must close its socket");
    assert.deepEqual(sockets[0].sent, []);
    assert.equal(sockets[1].closed, false);
    assert.deepEqual(sockets[1].sent, [["set_active_chat", { chat_id: "chat-a" }]]);
    client.endInteractiveViewerSession();
    assert.equal(sockets[1].closed, true, "the active socket remains tracked for exit");
  });
});
