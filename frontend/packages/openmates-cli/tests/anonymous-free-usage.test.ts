/**
 * Focused anonymous free-usage CLI contract tests.
 *
 * Purpose: verify logged-out CLI behavior before the web/native slices run.
 * Scope: public status discovery, self-host/inactive blocking, anonymous ID
 * persistence, and file-upload signup gating before file reads.
 * Run: npm run build && node --test tests/anonymous-free-usage.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { execFile, spawnSync } from "node:child_process";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { mkdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);
const PACKAGE_ROOT = fileURLToPath(new URL("..", import.meta.url));

interface AnonymousMockOptions {
  statusCode?: number;
  statusBody?: unknown;
  skillStatusCode?: number;
  skillBody?: unknown;
}

async function readJsonBody(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk));
  return JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<string, unknown>;
}

function writeJson(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(value));
}

async function withAnonymousMockApi<T>(
  options: AnonymousMockOptions,
  run: (params: { apiUrl: string; tempHome: string; requests: Record<string, unknown>[]; httpRequests: Array<{ path: string; authorization: string | undefined }>; skillRequests: Array<{ body: Record<string, unknown>; anonymousId: string | undefined }> }) => T | Promise<T>,
): Promise<T> {
  const requests: Record<string, unknown>[] = [];
  const httpRequests: Array<{ path: string; authorization: string | undefined }> = [];
  const skillRequests: Array<{ body: Record<string, unknown>; anonymousId: string | undefined }> = [];
  const tempHome = join(tmpdir(), `openmates-cli-anonymous-free-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  mkdirSync(tempHome, { recursive: true });
  const server = createServer(async (request, response) => {
    httpRequests.push({ path: request.url ?? "", authorization: request.headers.authorization });
    try {
      if (request.method === "GET" && request.url === "/v1/anonymous/free-usage/status") {
        writeJson(response, options.statusCode ?? 200, options.statusBody ?? {
          active: true,
          reason: null,
          reset_at: "2026-06-17T00:00:00+00:00",
          cta: "Sign up to keep using OpenMates",
        });
        return;
      }
      if (request.method === "POST" && request.url === "/v1/anonymous/chat/stream") {
        const body = await readJsonBody(request);
        requests.push(body);
        writeJson(response, 200, {
          status: "completed",
          chatId: body.client_chat_id,
          messageId: body.client_message_id,
          assistant: "anonymous inference ok",
          category: "general_knowledge",
          modelName: "test-model",
          followUpSuggestions: [],
        });
        return;
      }
      if (request.method === "POST" && ["/v1/anonymous/apps/web/skills/search", "/v1/anonymous/apps/ai/skills/decide"].includes(request.url ?? "")) {
        const body = await readJsonBody(request);
        skillRequests.push({ body, anonymousId: request.headers["x-openmates-anonymous-id"] as string | undefined });
        writeJson(response, options.skillStatusCode ?? 200, options.skillBody ?? {
          success: true, data: { results: [{ title: "Example" }] }, credits_charged: 6,
        });
        return;
      }
      writeJson(response, 404, { detail: "Not Found" });
    } catch (error) {
      writeJson(response, 500, { detail: String(error) });
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    return await run({ apiUrl: `http://127.0.0.1:${address.port}`, tempHome, requests, httpRequests, skillRequests });
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    rmSync(tempHome, { recursive: true, force: true });
  }
}

async function runCliJson(args: string[], env: Record<string, string>): Promise<Record<string, unknown>> {
  const { stdout } = await execFileAsync("node", ["dist/cli.js", ...args], {
    cwd: PACKAGE_ROOT,
    encoding: "utf-8",
    env: { ...process.env, OPENMATES_API_KEY: "", TERM: "dumb", ...env },
    timeout: 15_000,
  });
  return JSON.parse(stdout) as Record<string, unknown>;
}

async function runCliExpectError(args: string[], env: Record<string, string>): Promise<string> {
  try {
    await execFileAsync("node", ["dist/cli.js", ...args], {
      cwd: PACKAGE_ROOT,
      encoding: "utf-8",
      env: { ...process.env, OPENMATES_API_KEY: "", TERM: "dumb", ...env },
      timeout: 15_000,
    });
  } catch (error) {
    const result = error as { stderr?: string };
    return result.stderr ?? "";
  }
  assert.fail("Expected CLI command to fail");
}

describe("anonymous free usage CLI", () => {
  // contract-test: direct surface=cli assertions=billing.anonymous.hard-capped-provider-metering
  it("runs an inline account-free app skill while logged out with the anonymous identity", async () => {
    await withAnonymousMockApi({}, async ({ apiUrl, tempHome, skillRequests }) => {
      const result = await runCliJson(
        ["apps", "web", "search", "--query", "OpenMates", "--json", "--api-url", apiUrl],
        { HOME: tempHome, USERPROFILE: tempHome },
      );
      assert.equal(result.credits_charged, 6);
      assert.deepEqual(skillRequests[0].body, { requests: [{ query: "OpenMates" }] });
      assert.ok(skillRequests[0].anonymousId);
      const diskState = JSON.parse(readFileSync(join(tempHome, ".openmates", "anonymous.json"), "utf-8")) as { anonymousId?: string };
      assert.equal(skillRequests[0].anonymousId, diskState.anonymousId);
    });
  });

  // contract-test: direct surface=cli assertions=billing.anonymous.hard-capped-provider-metering
  it("shows shared-budget rejection for a logged-out app skill", async () => {
    await withAnonymousMockApi(
      { skillStatusCode: 429, skillBody: { detail: { code: "budget_exhausted", message: "Create an account to keep using OpenMates." } } },
      async ({ apiUrl, tempHome, skillRequests }) => {
        const stderr = await runCliExpectError(
          ["apps", "web", "search", "--query", "OpenMates", "--json", "--api-url", apiUrl],
          { HOME: tempHome, USERPROFILE: tempHome },
        );
        assert.match(stderr, /Create an account to keep using OpenMates/);
        assert.match(stderr, /signup required/i);
        assert.doesNotMatch(stderr, /failed/i);
        assert.equal(skillRequests.length, 1);
      },
    );
  });

  // contract-test: supporting surface=cli assertions=ai-decide.request.bounded,ai-decide.answers.typed
  it("dispatches generated ai.decide with nested questions and the persisted guest identity", async () => {
    const input = { state: { health: 10, enemyNearby: true }, questions: { retreat: { type: "noul", instructions: "Should the player retreat?" } } };
    await withAnonymousMockApi(
      { skillBody: { success: true, data: { success: true, model: "test-decision-model", answers: { retreat: { type: "noul", noul: 0.9 } }, usage: { input_tokens: 100, output_tokens: 5, credits: 1, complete: true } }, credits_charged: 1 } },
      async ({ apiUrl, tempHome, skillRequests }) => {
        const result = await runCliJson(["apps", "ai", "decide", "--input", JSON.stringify(input), "--json", "--api-url", apiUrl], { HOME: tempHome, USERPROFILE: tempHome });
        assert.equal(result.credits_charged, 1);
        assert.deepEqual(skillRequests[0].body, input);
        assert.ok(skillRequests[0].anonymousId);
      },
    );
  });

  // contract-test: supporting surface=cli assertions=ai-decide.images.inline,sdk.anonymous.execution
  it("forwards generated ai.decide --input image assets unchanged without auth or allowance preflights", async () => {
    const imageId = "4a3a8538-f152-423f-9fb3-fc9dce5db19c";
    // Synthetic base64 is a transport fixture, not evidence of image validation.
    const input = {
      state: { screenshot_id: imageId, player: { health: 10 } },
      questions: { retreat: { type: "noul", instructions: `Inspect screenshot ${imageId}. Should the player retreat?` } },
      assets: { [imageId]: { type: "image", format: "png", data_base64: "AQIDBA==" } },
    };
    await withAnonymousMockApi(
      { skillBody: { success: true, data: { answers: { retreat: { type: "noul", noul: 0.9 } } }, credits_charged: 1 } },
      async ({ apiUrl, tempHome, skillRequests, httpRequests }) => {
        const args = ["apps", "ai", "decide", "--input", JSON.stringify(input), "--json", "--api-url", apiUrl];
        for (let turn = 0; turn < 2; turn++) {
          const result = await runCliJson(args, { HOME: tempHome, USERPROFILE: tempHome });
          assert.equal(result.credits_charged, 1);
        }
        assert.deepEqual(httpRequests.map(request => request.path), [
          "/v1/anonymous/apps/ai/skills/decide", "/v1/anonymous/apps/ai/skills/decide",
        ]);
        assert.ok(httpRequests.every(request => request.authorization === undefined));
        assert.equal(skillRequests.length, 2);
        const diskState = JSON.parse(readFileSync(join(tempHome, ".openmates", "anonymous.json"), "utf-8")) as { anonymousId?: string };
        assert.ok(diskState.anonymousId);
        for (const request of skillRequests) {
          assert.deepEqual(request.body, input);
          assert.equal(request.anonymousId, diskState.anonymousId);
        }
      },
    );
  });

  // contract-test: supporting surface=cli assertions=ai-decide.failures.distinct
  it("keeps real provider failures distinct from signup-required allowance refusal", async () => {
    await withAnonymousMockApi(
      { skillStatusCode: 503, skillBody: { detail: { code: "decision_provider_unavailable", message: "Decision provider unavailable. Please try again later." } } },
      async ({ apiUrl, tempHome }) => {
        const stderr = await runCliExpectError(["apps", "web", "search", "--query", "OpenMates", "--json", "--api-url", apiUrl], { HOME: tempHome, USERPROFILE: tempHome });
        assert.match(stderr, /provider unavailable/i);
        assert.doesNotMatch(stderr, /Create an account/i);
      },
    );
  });

  // contract-test: direct surface=cli assertions=billing.anonymous.hard-capped-provider-metering
  it("discovers active status, sends anonymous ID, and persists it locally", async () => {
    await withAnonymousMockApi({}, async ({ apiUrl, tempHome, requests }) => {
      const first = await runCliJson(
        ["chats", "new", "Reply with exactly: anonymous inference ok", "--json", "--api-url", apiUrl],
        { HOME: tempHome, USERPROFILE: tempHome },
      );
      assert.equal(first.status, "completed");
      assert.equal(first.assistant, "anonymous inference ok");
      assert.equal(requests.length, 1);
      const anonymousId = requests[0].anonymous_id;
      assert.equal(typeof anonymousId, "string");

      const diskState = JSON.parse(readFileSync(join(tempHome, ".openmates", "anonymous.json"), "utf-8")) as { anonymousId?: string };
      assert.equal(diskState.anonymousId, anonymousId);

      await runCliJson(
        ["chats", "new", "Send a second anonymous message", "--json", "--api-url", apiUrl],
        { HOME: tempHome, USERPROFILE: tempHome },
      );
      assert.equal(requests.length, 2);
      assert.equal(requests[1].anonymous_id, anonymousId);
    });
  });

  // contract-test: supporting surface=cli assertions=billing.anonymous.hard-capped-provider-metering
  it("sends anonymous Learning Mode context when requested", async () => {
    await withAnonymousMockApi({}, async ({ apiUrl, tempHome, requests }) => {
      await runCliJson(
        [
          "chats",
          "new",
          "Help me understand fractions",
          "--learning-mode",
          "--age-group",
          "10_12",
          "--json",
          "--api-url",
          apiUrl,
        ],
        { HOME: tempHome, USERPROFILE: tempHome },
      );

      assert.equal(requests.length, 1);
      assert.deepEqual(requests[0].learning_mode, {
        enabled: true,
        age_group: "10_12",
        source: "anonymous_session",
      });
    });
  });

  // contract-test: supporting surface=cli assertions=billing.anonymous.hard-capped-provider-metering
  it("omits anonymous Learning Mode context by default", async () => {
    await withAnonymousMockApi({}, async ({ apiUrl, tempHome, requests }) => {
      await runCliJson(
        ["chats", "new", "Hello", "--json", "--api-url", apiUrl],
        { HOME: tempHome, USERPROFILE: tempHome },
      );

      assert.equal(requests.length, 1);
      assert.equal(Object.hasOwn(requests[0], "learning_mode"), false);
    });
  });

  // contract-test: direct surface=cli assertions=billing.anonymous.hard-capped-provider-metering
  it("blocks inactive anonymous status before chat execution", async () => {
    await withAnonymousMockApi(
      { statusBody: { active: false, reason: "inactive", reset_at: "2026-06-17T00:00:00+00:00", cta: "Create an account to keep using OpenMates." } },
      async ({ apiUrl, tempHome, requests }) => {
        const stderr = await runCliExpectError(
          ["chats", "new", "hello", "--json", "--api-url", apiUrl],
          { HOME: tempHome, USERPROFILE: tempHome },
        );
        assert.match(stderr, /Create an account to keep using OpenMates/);
        assert.equal(requests.length, 0);
      },
    );
  });

  // contract-test: direct surface=cli assertions=billing.anonymous.hard-capped-provider-metering
  it("blocks self-hosted anonymous status before chat execution", async () => {
    await withAnonymousMockApi(
      { statusCode: 404, statusBody: { detail: "Feature not available on this server edition" } },
      async ({ apiUrl, tempHome, requests }) => {
        const stderr = await runCliExpectError(
          ["chats", "new", "hello", "--json", "--api-url", apiUrl],
          { HOME: tempHome, USERPROFILE: tempHome },
        );
        assert.match(stderr, /not available on this server/);
        assert.equal(requests.length, 0);
      },
    );
  });

  // contract-test: direct surface=cli assertions=billing.anonymous.hard-capped-provider-metering
  it("returns signup_required before reading anonymous file references", () => {
    const tempHome = join(tmpdir(), `openmates-cli-anonymous-file-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    mkdirSync(tempHome, { recursive: true });
    try {
      const result = spawnSync(
        "node",
        ["dist/cli.js", "chats", "new", "summarize @/tmp/openmates-anonymous-file-that-must-not-be-read.txt", "--json"],
        {
          cwd: PACKAGE_ROOT,
          encoding: "utf-8",
          env: { ...process.env, TERM: "dumb", HOME: tempHome, USERPROFILE: tempHome },
          timeout: 15_000,
        },
      );
      assert.equal(result.status, 0, result.stderr);
      const parsed = JSON.parse(result.stdout) as { status?: string; reason?: string; signup_required?: boolean };
      assert.equal(parsed.status, "signup_required");
      assert.equal(parsed.reason, "file_upload_requires_signup");
      assert.equal(parsed.signup_required, true);
    } finally {
      rmSync(tempHome, { recursive: true, force: true });
    }
  });
});
