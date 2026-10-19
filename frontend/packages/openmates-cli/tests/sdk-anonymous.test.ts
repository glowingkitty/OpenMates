/** Anonymous SDK execution and signup errors. No real inference or account state. */
// contract-test-file: tooling
import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { OpenMates, OpenMatesApiError, OpenMatesConfigError, OpenMatesSignupRequiredError } from "../src/sdk.ts";

async function withServer(run: (apiUrl: string, requests: Array<{path: string; headers: Record<string, unknown>; body: any}>, reply: (status: number, data: unknown, raw?: boolean) => void) => Promise<void>) {
  const requests: Array<{path: string; headers: Record<string, unknown>; body: any}> = [];
  let status = 200;
  let rawReply = false;
  let data: unknown = { assistant: "Hello", results: ["match"] };
  const server = createServer(async (req, res) => {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    requests.push({ path: req.url!, headers: req.headers, body: raw ? JSON.parse(raw) : undefined });
    res.writeHead(status, { "content-type": "application/json" });
    res.end(rawReply ? String(data) : JSON.stringify(data));
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try { await run(`http://127.0.0.1:${address.port}`, requests, (nextStatus, nextData, raw = false) => { status = nextStatus; data = nextData; rawReply = raw; }); }
  finally { await new Promise<void>(resolve => server.close(() => resolve())); }
}

// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,sdk.anonymous.execution
test("anonymous generated skills, chat and status share a persistent identity without credentials or preflights", async () => {
  const directory = mkdtempSync(join(tmpdir(), "sdk-anonymous-"));
  try {
    await withServer(async (apiUrl, requests) => {
      const options = { apiUrl, anonymous: true, deviceIdPath: join(directory, "device-id") };
      const first = new OpenMates(options);
      const second = new OpenMates(options);
      await first.apps.web.search({ query: "OpenMates" });
      const chat = await second.chats.send("Hello", { history: [{ role: "assistant", content: "Earlier", created_at: 5, private: "strip" }] });
      assert.equal(chat.content, "Hello");
      assert.equal(chat.assistant, "Hello");
      await first.anonymous.status();
      assert.deepEqual(requests.map(r => r.path), ["/v1/anonymous/apps/web/skills/search", "/v1/anonymous/chat/stream", "/v1/anonymous/free-usage/status"]);
      const id = requests[0].headers["x-openmates-anonymous-id"];
      assert.ok(id);
      for (const req of requests) {
        assert.equal(req.headers["x-openmates-anonymous-id"], id);
        assert.equal(req.headers.authorization, undefined);
      }
      assert.equal(requests[1].headers.accept, "application/json");
      assert.equal(requests[1].body.anonymous_id, id);
      assert.match(requests[1].body.client_chat_id, /^[a-f0-9-]{36}$/);
      assert.deepEqual(requests[1].body.message_history, [{ role: "assistant", content: "Earlier", created_at: 5 }]);
    });
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

// contract-test: supporting surface=sdks.npm assertions=ai-decide.images.inline,sdk.anonymous.execution
test("anonymous generated ai.decide forwards inline image assets unchanged without preflights", async () => {
  const imageId = "4a3a8538-f152-423f-9fb3-fc9dce5db19c";
  // Synthetic bytes test transport only; the mock does not validate image decoding.
  const input = {
    state: { screenshot_id: imageId, player: { health: 10 } },
    questions: { retreat: { type: "noul", instructions: `Evaluate the screenshot ${imageId} and player health. Should the player retreat?` } },
    assets: { [imageId]: { type: "image", format: "png", data_base64: "AQIDBA==" } },
  };
  await withServer(async (apiUrl, requests, reply) => {
    const expected = { success: true, answers: { retreat: { type: "noul", noul: 0.9 } } };
    reply(200, expected);
    const options = { apiUrl, anonymous: true, anonymousId: "decision-image-guest", deviceId: "decision-image-device" };
    const first = new OpenMates(options);
    const second = new OpenMates(options);
    assert.deepEqual(await first.apps.ai.decide(input), expected);
    assert.deepEqual(await second.apps.ai.decide(input), expected);
    assert.deepEqual(requests.map(request => request.path), [
      "/v1/anonymous/apps/ai/skills/decide", "/v1/anonymous/apps/ai/skills/decide",
    ]);
    for (const request of requests) {
      assert.deepEqual(request.body, input);
      assert.equal(request.headers.authorization, undefined);
      assert.equal(request.headers["x-openmates-anonymous-id"], "decision-image-guest");
    }
  });
});

// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,sdk.anonymous.execution
test("automatic keyless mode and explicit free-only mode preserve credential boundaries", async () => {
  const previous = process.env.OPENMATES_API_KEY;
  try {
    delete process.env.OPENMATES_API_KEY;
    await withServer(async (apiUrl, requests, reply) => {
      const guest = new OpenMates({ apiUrl, deviceId: "guest" });
      await guest.apps.web.search({ query: "test" });
      assert.match(requests[0].path, /anonymous/);
      process.env.OPENMATES_API_KEY = "environment-secret";
      await new OpenMates({ apiUrl, deviceId: "guest", anonymous: true }).apps.web.search({ query: "free" });
      assert.equal(requests[1].headers.authorization, undefined);
      assert.throws(() => new OpenMates({ anonymous: true, apiKey: "explicit-key" }), OpenMatesConfigError);
      reply(401, { detail: "invalid credential" });
      await assert.rejects(new OpenMates({ apiUrl, deviceId: "guest" }).apps.web.search({ query: "auth" }), error => error instanceof OpenMatesApiError && error.status === 401 && !(error instanceof OpenMatesSignupRequiredError));
      assert.equal(requests[2].path, "/v1/apps/web/skills/search");
      assert.equal(requests[2].headers.authorization, "Bearer environment-secret");
      reply(429, { detail: { code: "budget_exhausted" } });
      await assert.rejects(new OpenMates({ apiUrl, apiKey: "explicit-key", deviceId: "guest" }).apps.web.search({ query: "auth" }), error => error instanceof OpenMatesApiError && !(error instanceof OpenMatesSignupRequiredError));
      assert.equal(requests.length, 4);
    });
  } finally { if (previous === undefined) delete process.env.OPENMATES_API_KEY; else process.env.OPENMATES_API_KEY = previous; }
});

// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity,sdk.anonymous.execution
test("anonymous chat rejects private options, invalid histories and private account routes before sending", async () => {
  await withServer(async (apiUrl, requests) => {
    const client = new OpenMates({ apiUrl, anonymous: true, anonymousId: "stable-id", deviceId: "device" });
    for (const options of [{ saveToAccount: true }, { model: "override" }, { goal: "goal" }, { memoryIds: [] }, { teamId: "team" }, { focusMode: {} }, { connectedAccountDirectory: [] }, { chatId: "saved" }]) {
      await assert.rejects(client.chats.send("hello", options as any), OpenMatesConfigError);
    }
    for (const history of [{ messages: "bad" }, {}, "bad", 3, false, null, [null], ["bad"]]) {
      await assert.rejects(client.chats.send("hello", { history: history as any }), OpenMatesConfigError);
    }
    await assert.rejects(client.chats.send("hello", { history: [{ role: "system", content: "private" }] }), OpenMatesConfigError);
    await assert.rejects(client.chats.send("hello", { history: Array(51).fill({ role: "user", content: "hi" }) }), OpenMatesConfigError);
    await assert.rejects(client.chats.send("x".repeat(20_001)), OpenMatesConfigError);
    await assert.rejects(client.request("/v1/sdk/private", {}), OpenMatesConfigError);
    await assert.rejects(client.get("/v1/sdk/private"), OpenMatesConfigError);
    await assert.rejects(client.apps.ai.ask({ prompt: "hello" }), /chats.send/);
    assert.equal(requests.length, 0);
    for (const anonymousId of ["", "x".repeat(129), "bad\nheader"]) assert.throws(() => new OpenMates({ anonymousId, deviceId: "test" }), OpenMatesConfigError);
  });
});

// contract-test: direct surface=sdks.npm assertions=sdk.anonymous.signup-required
test("quota denials require signup while provider failures remain distinguishable", async () => {
  await withServer(async (apiUrl, requests, reply) => {
    const client = new OpenMates({ apiUrl, anonymous: true, deviceId: "guest" });
    for (const code of ["budget_exhausted", "per_identity_exhausted", "inactive", "signup_required"]) {
      reply(code === "signup_required" ? 403 : 429, { detail: { code } });
      await assert.rejects(client.apps.web.search({ query: "test" }), error => error instanceof OpenMatesSignupRequiredError && error.signupRequired && error.code === code && /free allowance.*Create.*account/i.test(error.message));
    }
    reply(403, { detail: "signup_required" });
    await assert.rejects(client.chats.send("Hello"), error => error instanceof OpenMatesSignupRequiredError && error.code === "signup_required" && error.reason === "signup_required");
    reply(429, { detail: { signup_required: true, code: "future_limit", reason: "limited" } });
    await assert.rejects(client.chats.send("Hello"), error => error instanceof OpenMatesSignupRequiredError && error.reason === "limited");
    for (const status of [401, 503]) {
      reply(status, { detail: { code: "provider_unavailable" } });
      await assert.rejects(client.chats.send("Hello"), error => error instanceof OpenMatesApiError && error.status === status && !(error instanceof OpenMatesSignupRequiredError));
    }
    for (const body of ["", "<html>Provider unavailable</html>"]) {
      reply(503, body, true);
      await assert.rejects(client.chats.send("Hello"), error => error instanceof OpenMatesApiError && error.status === 503 && !(error instanceof OpenMatesSignupRequiredError));
    }
    assert.equal(requests.length, 10);
  });
});

// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
test("anonymous network failures are not signup errors", async () => {
  const client = new OpenMates({ anonymous: true, apiUrl: "http://127.0.0.1:0", deviceId: "test" });
  await assert.rejects(client.chats.send("hello"), error => error instanceof TypeError && !(error instanceof OpenMatesSignupRequiredError));
});
