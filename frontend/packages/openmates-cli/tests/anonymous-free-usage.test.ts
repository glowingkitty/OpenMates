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
  run: (params: { apiUrl: string; tempHome: string; requests: Record<string, unknown>[] }) => T | Promise<T>,
): Promise<T> {
  const requests: Record<string, unknown>[] = [];
  const tempHome = join(tmpdir(), `openmates-cli-anonymous-free-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  mkdirSync(tempHome, { recursive: true });
  const server = createServer(async (request, response) => {
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
      writeJson(response, 404, { detail: "Not Found" });
    } catch (error) {
      writeJson(response, 500, { detail: String(error) });
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    return await run({ apiUrl: `http://127.0.0.1:${address.port}`, tempHome, requests });
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
    env: { ...process.env, TERM: "dumb", ...env },
    timeout: 15_000,
  });
  return JSON.parse(stdout) as Record<string, unknown>;
}

async function runCliExpectError(args: string[], env: Record<string, string>): Promise<string> {
  try {
    await execFileAsync("node", ["dist/cli.js", ...args], {
      cwd: PACKAGE_ROOT,
      encoding: "utf-8",
      env: { ...process.env, TERM: "dumb", ...env },
      timeout: 15_000,
    });
  } catch (error) {
    const result = error as { stderr?: string };
    return result.stderr ?? "";
  }
  assert.fail("Expected CLI command to fail");
}

describe("anonymous free usage CLI", () => {
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
