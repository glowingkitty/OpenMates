// contract-test-file: infrastructure
import { it } from "node:test";
import assert from "node:assert/strict";
import { OpenMatesClient } from "../src/client.ts";

// contract-test: supporting surface=cli assertions=notifications.delivery.email-enabled
it("reads durable email settings without sending a preference write", async () => {
  const client = Object.create(OpenMatesClient.prototype) as OpenMatesClient;
  const sent: Array<[string, unknown]> = [];
  let closed = false;
  const snapshot = {
    enabled: true,
    preferences: { aiResponses: false, backupReminder: true },
    choices: { aiResponses: { source: "user", value: false } },
    backup_reminder_interval_days: 28,
  };
  (client as any).openWsClient = async () => ({
    ws: {
      waitForMessage: async (type: string, match: (payload: unknown) => boolean) => {
        assert.equal(type, "email_notification_settings_snapshot");
        assert.equal(match({ ...snapshot, request_id: "different-request" }), false);
        await Promise.resolve();
        const requestId = (sent[0]?.[1] as { request_id: string })?.request_id;
        assert.match(requestId, /^[0-9a-f-]{36}$/);
        assert.equal(match({ ...snapshot, request_id: requestId }), true);
        return { payload: { ...snapshot, request_id: requestId } };
      },
      sendAsync: async (type: string, payload: unknown) => { sent.push([type, payload]); },
      close: () => { closed = true; },
    },
  });

  assert.deepEqual(await client.getEmailNotificationSettings(), snapshot);
  assert.equal(sent[0][0], "email_notification_settings_get");
  assert.deepEqual(Object.keys(sent[0][1] as object), ["request_id"]);
  assert.equal(closed, true);
});

// contract-test: supporting surface=cli assertions=notifications.delivery.email-enabled
it("writes email settings only after its own acknowledgement", async () => {
  const client = Object.create(OpenMatesClient.prototype) as OpenMatesClient;
  const sent: Array<[string, Record<string, unknown>]> = [];
  let closed = false;
  (client as any).openWsClient = async () => ({
    ws: {
      waitForMessage: async (type: string, match: (payload: unknown) => boolean) => {
        assert.equal(type, "email_notification_settings_ack");
        await Promise.resolve();
        const requestId = sent[0]?.[1].request_id;
        assert.equal(match({ success: true, request_id: "another-write" }), false);
        assert.equal(match({ success: true, request_id: requestId }), true);
        return { payload: { success: true, request_id: requestId } };
      },
      sendAsync: async (type: string, payload: Record<string, unknown>) => { sent.push([type, payload]); },
      close: () => { closed = true; },
    },
  });

  const response = await client.updateEmailNotificationSettings({ preferences: { aiResponses: false } });
  assert.deepEqual(response, { success: true, request_id: sent[0][1].request_id });
  assert.equal(sent[0][0], "email_notification_settings");
  assert.deepEqual(sent[0][1].preferences, { aiResponses: false });
  assert.match(String(sent[0][1].request_id), /^[0-9a-f-]{36}$/);
  assert.equal(closed, true);
});

// contract-test: supporting surface=cli assertions=notifications.delivery.email-enabled
it("surfaces a correlated settings rejection without waiting for an ACK", async () => {
  const client = Object.create(OpenMatesClient.prototype) as OpenMatesClient;
  let closed = false;
  let sentRequestId: string | undefined;
  (client as any).openWsClient = async () => ({
    ws: {
      waitForMessage: async (type: string, match: (payload: unknown) => boolean) => {
        assert.equal(type, "email_notification_settings_ack");
        await Promise.resolve();
        assert.equal(match({ request_id: "different-request" }), false);
        assert.equal(match({ request_id: sentRequestId }), true);
        throw new Error("Invalid notification setting.");
      },
      sendAsync: async (_type: string, payload: { request_id: string }) => { sentRequestId = payload.request_id; },
      close: () => { closed = true; },
    },
  });

  await assert.rejects(
    client.updateEmailNotificationSettings({ enabled: true }),
    /Invalid notification setting\./,
  );
  assert.equal(closed, true);
});
