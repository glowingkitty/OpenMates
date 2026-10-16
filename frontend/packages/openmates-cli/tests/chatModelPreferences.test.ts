import assert from "node:assert/strict";
import { test } from "node:test";
import { createDecipheriv } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { createChatModelPreferences, type ChatModelPreferenceClient } from "../src/chatModelPreferences.js";
import { decryptWithAesGcmCombined, encryptWithAesGcmCombined } from "../src/crypto.js";
import type { OpenMatesSession } from "../src/storage.js";

function session(owner = "owner-a"): OpenMatesSession {
  return {
    apiUrl: "https://api.openmates.test", sessionId: owner, wsToken: null,
    cookies: {}, masterKeyExportedB64: Buffer.alloc(32, 7).toString("base64"),
    hashedEmail: owner, userEmailSalt: "salt", createdAt: 1,
    authorizerDeviceName: null, autoLogoutMinutes: null, activeTeamId: null,
  };
}
function setup() {
  const directory = mkdtempSync(join(tmpdir(), "openmates-model-prefs-"));
  const previous = process.env.OPENMATES_STATE_DIR;
  process.env.OPENMATES_STATE_DIR = directory;
  let active = session();
  let online = true;
  let calls = 0;
  const remote = new Map<string, { ciphertext: string; version: number }>();
  const client: ChatModelPreferenceClient = {
    apiUrl: active.apiUrl,
    hasSession: () => true,
    getSession: () => active,
    resolveTeamContext: () => active.activeTeamId ?? null,
    async getChatModelCatalogSources() {
      return {
        all: { apps: { ai: { skills: [{ id: "ask", models: [
          { id: "alpha", name: "Alpha", provider_id: "provider", provider_name: "Provider", description: "A" },
          { id: "beta", name: "Beta", provider_id: "provider", provider_name: "Provider", description: "B" },
        ] }] } } },
        available: { apps: { ai: { skills: [{ id: "ask", models: [
          { id: "alpha", provider_id: "provider" }, { id: "beta", provider_id: "provider" },
        ] }] } } },
        routes: { data: [{ id: "provider/alpha", created: 1770000000, openmates: { capability_level: "high" } }] },
        health: { providers: { provider: { status: "healthy" } } },
      };
    },
    async getChatModelPreference(chatId) {
      calls++;
      if (!online) throw new Error("offline");
      return remote.get(chatId) ?? null;
    },
    async compareAndSetChatModelPreference(chatId, ciphertext, expectedVersion) {
      calls++;
      if (!online) throw new Error("offline");
      const old = remote.get(chatId);
      if ((old?.version ?? 0) !== expectedVersion) return null;
      const next = { ciphertext, version: expectedVersion + 1 };
      remote.set(chatId, next);
      return next;
    },
  };
  const close = () => {
    if (previous === undefined) delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR = previous;
    rmSync(directory, { recursive: true, force: true });
  };
  return {
    client, remote, directory, close,
    setOnline(value: boolean) { online = value; },
    setOwner(value: string) { active = session(value); },
    get calls() { return calls; },
  };
}

// contract-test: supporting surface=cli assertions=ai-model-routing.catalog.public-read-only,ai-model-routing.catalog.capability-recommendation-variants
test("catalog keeps only live routable exact choices available", async () => {
  const fixture = setup();
  try {
    const models = await createChatModelPreferences(fixture.client).catalog();
    assert.deepEqual(models.map(model => [model.id, model.available]), [
      ["provider/alpha", true], ["provider/beta", false],
    ]);
    assert.equal(models[0].capability, "high");
    assert.equal(models[0].releaseDate, "2026-02-02");
  } finally { fixture.close(); }
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
test("offline exact selection is encrypted locally and CAS synced on reconnect", async () => {
  const fixture = setup();
  try {
    const service = createChatModelPreferences(fixture.client);
    fixture.setOnline(false);
    const pending = await service.select("chat-a", "provider/alpha");
    assert.equal(pending.pending, true);
    const local = readFileSync(join(fixture.directory, "chat_model_preferences.json"), "utf8");
    assert.doesNotMatch(local, /provider\/alpha|chat-a/);
    fixture.setOnline(true);
    const synced = await service.flushPending("chat-a");
    assert.equal(synced.pending, false);
    const encrypted = fixture.remote.get("chat-a");
    assert.ok(encrypted);
    const formatD = Buffer.from(encrypted.ciphertext, "base64");
    const webCompatible = createDecipheriv("aes-256-gcm", Buffer.alloc(32, 7), formatD.subarray(0, 12));
    webCompatible.setAuthTag(formatD.subarray(-16));
    const plain = Buffer.concat([webCompatible.update(formatD.subarray(12, -16)), webCompatible.final()]).toString("utf8");
    assert.equal(plain, '{"mode":"exact","model":"provider/alpha"}');
    assert.deepEqual(JSON.parse((await decryptWithAesGcmCombined(encrypted.ciphertext, Buffer.alloc(32, 7)))!), {
      mode: "exact", model: "provider/alpha",
    });
    assert.equal((await createChatModelPreferences(fixture.client).restore("chat-a")).selection, "provider/alpha");
    assert.equal((await service.restore("chat-b")).selection, "auto");
  } finally { fixture.close(); }
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
test("CAS conflict retries latest version while preserving local pending choice", async () => {
  const fixture = setup();
  try {
    const service = createChatModelPreferences(fixture.client);
    fixture.setOnline(false);
    await service.select("chat-c", "provider/alpha");
    fixture.remote.set("chat-c", {
      ciphertext: await encryptWithAesGcmCombined('{"mode":"auto"}', Buffer.alloc(32, 7)),
      version: 4,
    });
    fixture.setOnline(true);
    const result = await service.flushPending("chat-c");
    assert.equal(result.selection, "provider/alpha");
    assert.equal(result.pending, false);
    assert.equal(fixture.remote.get("chat-c")?.version, 5);
  } finally { fixture.close(); }
});

// contract-test: supporting surface=cli assertions=ai-model-routing.unavailable.notify-reset-auto,ai-model-routing.chat-selection.encrypted-user-chat-scope
test("unavailable exact route resets to Auto and syncs encrypted choice", async () => {
  const fixture = setup();
  try {
    const service = createChatModelPreferences(fixture.client);
    await service.select("chat-d", "provider/alpha");
    const result = await service.validate("chat-d", [{ id: "provider/alpha", available: false } as never]);
    assert.equal(result.reset, true);
    assert.equal(result.selection, "auto");
    assert.equal(fixture.remote.get("chat-d")?.version, 2);
  } finally { fixture.close(); }
});

// contract-test: supporting surface=cli assertions=ai-model-routing.unavailable.notify-reset-auto
test("cached provisional availability never resets a saved exact choice", async () => {
  const fixture = setup();
  try {
    const service = createChatModelPreferences(fixture.client);
    await service.select("chat-provisional", "provider/alpha");
    const provisional = Object.assign(
      [{ id: "provider/alpha", available: false } as never], { authoritative: false },
    );
    const result = await service.validate("chat-provisional", provisional);
    assert.equal(result.reset, false);
    assert.equal(result.selection, "provider/alpha");
    assert.equal(fixture.remote.get("chat-provisional")?.version, 1);
  } finally { fixture.close(); }
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
test("owner switch fences an in-flight preference restore", async () => {
  const fixture = setup();
  try {
    let resolve!: (value: { ciphertext: string; version: number }) => void;
    fixture.client.getChatModelPreference = async () => new Promise(done => { resolve = done; });
    const service = createChatModelPreferences(fixture.client);
    const pending = service.restore("chat-e");
    await new Promise(resolve => setImmediate(resolve));
    fixture.setOwner("owner-b");
    resolve({ ciphertext: await encryptWithAesGcmCombined('{"mode":"exact","model":"provider/alpha"}', Buffer.alloc(32, 7)), version: 1 });
    await assert.rejects(pending, /owner changed/);
    assert.equal(service.current("chat-e").selection, "auto");
  } finally { fixture.close(); }
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
test("local preferences remain separate when switching between signed-in owners", async () => {
  const fixture = setup();
  try {
    const service = createChatModelPreferences(fixture.client);
    fixture.setOnline(false);
    await service.select("shared-chat-id", "provider/alpha");
    fixture.setOwner("owner-b");
    assert.equal((await service.restore("shared-chat-id")).restored, false);
    await service.select("shared-chat-id", "provider/beta");
    fixture.setOwner("owner-a");
    assert.equal((await service.restore("shared-chat-id")).selection, "provider/alpha");
    fixture.setOwner("owner-b");
    assert.equal((await service.restore("shared-chat-id")).selection, "provider/beta");
  } finally { fixture.close(); }
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
test("cached restore returns before WS reply and publishes a newer remote version", async () => {
  const fixture = setup();
  try {
    await createChatModelPreferences(fixture.client).select("chat-refresh", "provider/alpha");
    let finish!: (value: { ciphertext: string; version: number }) => void;
    fixture.client.getChatModelPreference = async () => new Promise(done => { finish = done; });
    const next = createChatModelPreferences(fixture.client);
    let published!: (value: string) => void;
    const changed = new Promise<string>(resolve => { published = resolve; });
    next.subscribe("chat-refresh", state => {
      if (state.selection === "provider/beta") published(state.selection);
    });
    const restored = await next.restore("chat-refresh");
    assert.equal(restored.selection, "provider/alpha");
    assert.equal(restored.restored, true);
    await new Promise(resolve => setImmediate(resolve));
    finish({
      ciphertext: await encryptWithAesGcmCombined('{"mode":"exact","model":"provider/beta"}', Buffer.alloc(32, 7)),
      version: 2,
    });
    assert.equal(await changed, "provider/beta");
    assert.equal(next.current("chat-refresh").selection, "provider/beta");
  } finally { fixture.close(); }
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope,ai-model-routing.precedence.chat-over-tier-over-auto
test("server-confirmed missing preference caches encrypted Auto for cold offline restore", async () => {
  const fixture = setup();
  try {
    const first = createChatModelPreferences(fixture.client);
    assert.deepEqual(await first.restore("draft-no-choice"), {
      selection: "auto", pending: false, restored: true,
    });
    assert.equal(fixture.calls, 1);
    const raw = readFileSync(join(fixture.directory, "chat_model_preferences.json"), "utf8");
    assert.doesNotMatch(raw, /draft-no-choice|"mode":"auto"/);
    const record = Object.values(Object.values(JSON.parse(raw).owners)[0] as Record<string, {
      ciphertext: string; version: number; pending: boolean;
    }>)[0];
    assert.equal(record.version, 0);
    assert.equal(record.pending, false);
    assert.equal(await decryptWithAesGcmCombined(record.ciphertext, Buffer.alloc(32, 7)), '{"mode":"auto"}');

    fixture.setOnline(false);
    const cold = createChatModelPreferences(fixture.client);
    assert.deepEqual(await cold.restore("draft-no-choice"), {
      selection: "auto", pending: false, restored: true,
    });
    assert.equal((await createChatModelPreferences(fixture.client).restore("another-draft")).restored, false,
      "an unrelated offline chat must not infer a server-confirmed Auto choice");
  } finally { fixture.close(); }
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
test("server-confirmed null replaces a stale exact cache with revision-zero Auto", async () => {
  const fixture = setup();
  try {
    await createChatModelPreferences(fixture.client).select("deleted-choice", "provider/alpha");
    fixture.remote.delete("deleted-choice");
    const next = createChatModelPreferences(fixture.client);
    let notify!: (value: string) => void;
    const reconciled = new Promise<string>(resolve => { notify = resolve; });
    next.subscribe("deleted-choice", state => {
      if (state.selection === "auto" && state.restored) notify(state.selection);
    });
    assert.equal((await next.restore("deleted-choice")).selection, "provider/alpha");
    assert.equal(await reconciled, "auto");
    const raw = readFileSync(join(fixture.directory, "chat_model_preferences.json"), "utf8");
    const record = Object.values(Object.values(JSON.parse(raw).owners)[0] as Record<string, {
      ciphertext: string; version: number; pending: boolean;
    }>)[0];
    assert.equal(record.version, 0);
    assert.equal(record.pending, false);
    assert.equal(await decryptWithAesGcmCombined(record.ciphertext, Buffer.alloc(32, 7)), '{"mode":"auto"}');
    fixture.setOnline(false);
    assert.equal((await createChatModelPreferences(fixture.client).restore("deleted-choice")).selection, "auto");
  } finally { fixture.close(); }
});

// contract-test: supporting surface=cli assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope,ai-model-routing.precedence.chat-over-tier-over-auto
test("delayed null cannot overwrite another instance's pending exact choice", async () => {
  const fixture = setup();
  try {
    let releaseNull!: () => void;
    const deferredNull = new Promise<null>(resolve => { releaseNull = () => resolve(null); });
    let firstLookup = true;
    fixture.client.getChatModelPreference = async () => {
      if (firstLookup) { firstLookup = false; return deferredNull; }
      throw new Error("offline");
    };
    const first = createChatModelPreferences(fixture.client);
    const restoring = first.restore("draft-race");
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(firstLookup, false, "the first restore must be waiting on server confirmation");

    const second = createChatModelPreferences(fixture.client);
    assert.deepEqual(await second.select("draft-race", "provider/alpha"), {
      selection: "provider/alpha", pending: true, restored: true,
    });
    releaseNull();
    assert.deepEqual(await restoring, {
      selection: "provider/alpha", pending: true, restored: true,
    });
    const raw = readFileSync(join(fixture.directory, "chat_model_preferences.json"), "utf8");
    assert.doesNotMatch(raw, /draft-race|provider\/alpha/);
    const record = Object.values(Object.values(JSON.parse(raw).owners)[0] as Record<string, {
      ciphertext: string; version: number; pending: boolean;
    }>)[0];
    assert.equal(record.pending, true);
    assert.equal(await decryptWithAesGcmCombined(record.ciphertext, Buffer.alloc(32, 7)),
      '{"mode":"exact","model":"provider/alpha"}');
  } finally { fixture.close(); }
});
