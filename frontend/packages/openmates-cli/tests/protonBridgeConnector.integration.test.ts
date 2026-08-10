/**
 * Integration-style tests for Proton Bridge local connector primitives.
 *
 * Purpose: exercise fake IMAP validation, connector heartbeat/cleanup, bounded
 * local request output, and delayed-send undo behavior without real Proton data.
 * Security: fake credentials stay in test memory and are never sent to a server.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/protonBridgeConnector.integration.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type Server } from "node:net";
import { once } from "node:events";
import { setTimeout as sleep } from "node:timers/promises";

import {
  ProtonDelayedSendQueue,
  containsCredentialLikeField,
  parseProtonBridgeInfo,
  runProtonBridgeConnector,
  validateProtonBridgeImap,
  type ProtonLocalConnectorRegistration,
} from "../src/protonBridgeConnector.ts";

describe("Proton Bridge connector fake integration", () => {
  it("validates fake localhost IMAP and rejects non-localhost IMAP", async () => {
    await withFakeImapServer(async (port) => {
      const credentials = bridgeCredentials(port);
      await validateProtonBridgeImap(credentials, 1_000);
      await assert.rejects(
        () => validateProtonBridgeImap({ ...credentials, imapHost: "imap.example.test" }, 1_000),
        /must be localhost/,
      );
    });
  });

  it("registers online, sends heartbeat, marks offline, and cleans up started Bridge", async () => {
    await withFakeImapServer(async (port) => {
      const calls: string[] = [];
      const registrations: ProtonLocalConnectorRegistration[] = [];
      const result = await runProtonBridgeConnector(fakeConnectorClient(calls, registrations), {}, {
        platform: "linux",
        architecture: "x64",
        findExecutable: () => "/usr/bin/protonmail-bridge",
        spawnBridge: () => ({ startedByOpenMates: true, stop: () => calls.push("bridge:stop") }),
        captureBridgeInfo: async () => bridgeInfoFixture(port),
        heartbeatOnce: true,
        stdout: { log: () => undefined },
        stderr: { error: () => undefined },
      });

      assert.equal(result.connectedAccountId, "account-1");
      assert.deepEqual(result.capabilities, ["read"]);
      assert.deepEqual(calls, ["register", "heartbeat:online", "heartbeat:offline", "bridge:stop"]);
      assert.equal(registrations[0]?.execution_mode, "local_connector");
      assert.equal(registrations[0]?.metadata.bridge_host, "localhost");
      assert.equal(containsCredentialLikeField(registrations[0]), false);
      assert.doesNotMatch(JSON.stringify(registrations[0]), /bridge-secret|alice@example.test/);
    });
  });

  it("does not stop Bridge processes that OpenMates only attached to", async () => {
    await withFakeImapServer(async (port) => {
      const calls: string[] = [];
      await runProtonBridgeConnector(fakeConnectorClient(calls, []), {}, {
        platform: "linux",
        architecture: "x64",
        findExecutable: () => "/usr/bin/protonmail-bridge",
        spawnBridge: () => ({ startedByOpenMates: false, stop: () => calls.push("bridge:stop") }),
        captureBridgeInfo: async () => bridgeInfoFixture(port),
        heartbeatOnce: true,
        stdout: { log: () => undefined },
        stderr: { error: () => undefined },
      });
      assert.deepEqual(calls, ["register", "heartbeat:online", "heartbeat:offline"]);
    });
  });

  it("keeps fake read results bounded and free of credentials", () => {
    const credentials = parseProtonBridgeInfo(bridgeInfoFixture(1143));
    const results = buildBoundedFakeReadResults(credentials, [
      { from: "sender@example.test", subject: "Project update", snippet: "No secrets here" },
      { from: "other@example.test", subject: "Second", snippet: `must not leak ${credentials.imapPassword}` },
    ]);
    assert.equal(results.length, 2);
    assert.equal(containsCredentialLikeField(results), false);
    assert.doesNotMatch(JSON.stringify(results), /bridge-secret|alice@example.test/);
  });

  it("handles a local connector mail.search request and completes it without credentials", async () => {
    const calls: string[] = [];
    const completions: Array<Record<string, unknown>> = [];
    await runProtonBridgeConnector(fakeConnectorClient(calls, [], {
      request: {
        type: "local_connector_request",
        connector_session_id: "session-1",
        connected_account_id: "account-1",
        request_id: "mail_search_1",
        action: "mail.search",
        arguments: { query: "invoice", start_date: "2026-07-01", end_date: "2026-07-15", limit: 2 },
      },
      completions,
    }), {}, {
      platform: "linux",
      architecture: "x64",
      findExecutable: () => "/usr/bin/protonmail-bridge",
      spawnBridge: () => ({ startedByOpenMates: true, stop: () => calls.push("bridge:stop") }),
      captureBridgeInfo: async () => bridgeInfoFixture(1143),
      validateImap: async () => undefined,
      searchImap: async (_credentials, arguments_) => {
        assert.equal(arguments_.start_date, "2026-07-01");
        assert.equal(arguments_.end_date, "2026-07-15");
        return [{ subject: `Found ${arguments_.query}`, snippet: "A normal password reset email is not a Bridge credential." }];
      },
      localRequestOnce: true,
      stdout: { log: () => undefined },
      stderr: { error: () => undefined },
    });

    assert.equal(completions.length, 1);
    assert.equal(completions[0]?.status, "ok");
    assert.deepEqual(completions[0]?.result, { messages: [{ subject: "Found invoice", snippet: "A normal password reset email is not a Bridge credential." }] });
    assert.equal(containsCredentialLikeField(completions[0]), false);
    assert.deepEqual(calls, ["register", "heartbeat:online", "complete:mail_search_1", "heartbeat:offline", "bridge:stop"]);
  });

  it("queues fake SMTP send, supports cancellation, and disables undo after delivery", async () => {
    const delivered: unknown[] = [];
    const queue = new ProtonDelayedSendQueue<Record<string, unknown>>(5);
    const queued = queue.queue({ to: "recipient@example.test", subject: "Hello" }, async (payload) => {
      delivered.push(payload);
    }, 1_000);
    assert.equal(queued.status, "queued");
    assert.equal(queued.deliverAt, 1_005);
    const cancelled = queue.undo(queued.id);
    assert.equal(cancelled.status, "cancelled");
    assert.equal(cancelled.payload, undefined);
    await sleep(10);
    assert.deepEqual(delivered, []);

    const deliveredJob = queue.queue({ to: "recipient@example.test", subject: "Deliver" }, async (payload) => {
      delivered.push(payload);
    }, 2_000);
    await sleep(10);
    assert.equal(queue.get(deliveredJob.id)?.status, "delivered");
    assert.equal(queue.get(deliveredJob.id)?.payload, undefined);
    const afterDeliveryUndo = queue.undo(deliveredJob.id);
    assert.equal(afterDeliveryUndo.status, "delivered");
    assert.match(afterDeliveryUndo.undoDisabledReason ?? "", /cannot recall/);
    assert.equal(containsCredentialLikeField(afterDeliveryUndo), false);

    const failedJob = queue.queue({ to: "recipient@example.test", subject: "Fail" }, async () => {
      throw new Error("delivery failed");
    }, 3_000);
    await sleep(10);
    const failed = queue.get(failedJob.id);
    assert.equal(failed?.status, "cancelled");
    assert.equal(failed?.payload, undefined);
    assert.match(failed?.undoDisabledReason ?? "", /Delivery failed/);
  });
});

async function withFakeImapServer(run: (port: number) => Promise<void>): Promise<void> {
  const server = createServer((socket) => {
    socket.write("* OK fake Proton Bridge IMAP ready\r\n");
    socket.end();
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await run(address.port);
  } finally {
    await closeServer(server);
  }
}

async function closeServer(server: Server): Promise<void> {
  await new Promise<void>((resolve) => server.close(() => resolve()));
}

function bridgeInfoFixture(port: number): string {
  return `
Account: alice@example.test
IMAP Settings
Address: 127.0.0.1
Port: ${port}
Username: alice@example.test
Password: bridge-secret
SMTP Settings
Address: 127.0.0.1
Port: 1025
Username: alice@example.test
Password: smtp-secret
`;
}

function bridgeCredentials(port: number) {
  return parseProtonBridgeInfo(bridgeInfoFixture(port));
}

function fakeConnectorClient(
  calls: string[],
  registrations: ProtonLocalConnectorRegistration[],
  options: {
    request?: Record<string, unknown>;
    completions?: Array<Record<string, unknown>>;
  } = {},
) {
  return {
    async registerLocalConnectedAccountConnector(input: ProtonLocalConnectorRegistration) {
      calls.push("register");
      registrations.push(input);
      return { connected_account_id: "account-1", connector_session_id: "session-1", heartbeat_interval_ms: 1 };
    },
    async sendLocalConnectedAccountConnectorHeartbeat(input: { status: string }) {
      calls.push(`heartbeat:${input.status}`);
      return { ok: true };
    },
    async completeLocalConnectedAccountConnectorRequest(input: Record<string, unknown>) {
      calls.push(`complete:${input.request_id}`);
      options.completions?.push(input);
      return { accepted: true };
    },
    async openLocalConnectorWebSocket() {
      return {
        onLocalConnectorRequest(handler: (payload: Record<string, unknown>) => void | Promise<void>) {
          if (options.request) queueMicrotask(() => void handler(options.request!));
          return () => undefined;
        },
        close() {},
      } as never;
    },
  };
}

function buildBoundedFakeReadResults(
  credentials: { imapUsername: string; imapPassword: string },
  messages: Array<{ from: string; subject: string; snippet: string }>,
): Array<{ from: string; subject: string; snippet: string }> {
  return messages.slice(0, 5).map((message) => ({
    from: message.from.replace(credentials.imapUsername, "<account>"),
    subject: message.subject.slice(0, 200),
    snippet: message.snippet.replaceAll(credentials.imapPassword, "<redacted>").slice(0, 500),
  }));
}
