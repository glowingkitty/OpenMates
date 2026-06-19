/**
 * Unit tests for CLI argument parsing, blocked paths, URL derivation,
 * suggestion parsing, and new chat suggestion rendering.
 *
 * These run without network access — all network calls are expected to throw.
 *
 * Run: cd frontend/packages/openmates-cli && npm run build && node --test tests/cli.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { execFile, execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { promisify } from "node:util";
import { WebSocketServer } from "ws";

// Import from compiled dist — the .js extension imports in src/ require the build step
import {
  deriveAppUrl,
  MEMORY_TYPE_REGISTRY,
  serializeToYaml,
  getExtForLang,
  defaultCloneBranchForVersion,
  buildAssistantFeedbackDecision,
} from "../dist/index.js";

const execFileAsync = promisify(execFile);
const PACKAGE_ROOT = fileURLToPath(new URL("..", import.meta.url));
const REPO_ROOT = fileURLToPath(new URL("../../../..", import.meta.url));

function runCli(args: string[], env: Record<string, string> = {}): string {
  return execFileSync("node", ["dist/cli.js", ...args], {
    cwd: PACKAGE_ROOT,
    encoding: "utf-8",
    env: { ...process.env, TERM: "dumb", ...env },
    timeout: 15_000,
  });
}

function runCliWithoutSession(args: string[]): string {
  const tempHome = join(tmpdir(), `openmates-cli-no-session-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  mkdirSync(tempHome, { recursive: true });
  try {
    return runCli(args, { HOME: tempHome, USERPROFILE: tempHome });
  } finally {
    rmSync(tempHome, { recursive: true, force: true });
  }
}

function runCliWithoutSessionResult(args: string[]): { status: number | null; stdout: string; stderr: string } {
  const tempHome = join(tmpdir(), `openmates-cli-no-session-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  mkdirSync(tempHome, { recursive: true });
  try {
    const result = spawnSync("node", ["dist/cli.js", ...args], {
      cwd: PACKAGE_ROOT,
      encoding: "utf-8",
      env: { ...process.env, TERM: "dumb", HOME: tempHome, USERPROFILE: tempHome },
      timeout: 15_000,
    });
    return { status: result.status, stdout: result.stdout, stderr: result.stderr };
  } finally {
    rmSync(tempHome, { recursive: true, force: true });
  }
}

async function runCliWithEmptyCacheSession(
  apiUrl: string,
  args: string[],
): Promise<{ stderr: string; stdout: string }> {
  const tempHome = join(tmpdir(), `openmates-cli-empty-cache-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  const stateDir = join(tempHome, ".openmates");
  mkdirSync(stateDir, { recursive: true });
  writeFileSync(join(stateDir, "session.json"), `${JSON.stringify({
    apiUrl,
    sessionId: "session-1",
    wsToken: "ws-token",
    cookies: { auth_refresh_token: "refresh-token" },
    masterKeyExportedB64: Buffer.alloc(32).toString("base64"),
    hashedEmail: "hashed-email",
    userEmailSalt: "salt",
    createdAt: Date.now(),
    authorizerDeviceName: "test-device",
    autoLogoutMinutes: null,
  })}\n`);
  writeFileSync(join(stateDir, "sync_cache.json"), `${JSON.stringify({
    syncedAt: Date.now(),
    totalChatCount: 0,
    loadedChatCount: 0,
    chats: [],
    embeds: [],
    embedKeys: [],
  })}\n`);

  try {
    await execFileAsync("node", ["dist/cli.js", ...args], {
      cwd: PACKAGE_ROOT,
      encoding: "utf-8",
      env: { ...process.env, TERM: "dumb", HOME: tempHome, USERPROFILE: tempHome, OPENMATES_API_URL: apiUrl },
      timeout: 15_000,
    });
    assert.fail("restore should require local encrypted embed state");
  } catch (error) {
    return {
      stderr: (error as { stderr?: string }).stderr ?? String(error),
      stdout: (error as { stdout?: string }).stdout ?? "",
    };
  } finally {
    rmSync(tempHome, { recursive: true, force: true });
  }
}

function readRepoText(path: string): string {
  return readFileSync(join(REPO_ROOT, path), "utf-8");
}

describe("benchmark command", () => {
  it("is listed in global help", () => {
    const output = runCli(["help"]);
    assert.match(output, /openmates benchmark \[--help\]/);
  });

  it("prints model benchmark help", () => {
    const output = runCli(["benchmark", "--help"]);
    assert.match(output, /openmates benchmark model <provider\/model> \[provider\/model\.\.\.\]/);
    assert.match(output, /google\/gemini-3-flash-preview/);
    assert.match(output, /--compare/);
    assert.match(output, /--case/);
    assert.match(output, /--extensive-size/);
    assert.match(output, /--parallel/);
    assert.match(output, /--image/);
  });

  it("supports priced dry-run without login and uses Gemini 3 Flash as default judge", () => {
    const output = runCliWithoutSession([
      "benchmark",
      "model",
      "google/gemini-3.5-flash",
      "--dry-run",
      "--suite",
      "quick",
      "--json",
    ]);
    const data = JSON.parse(output) as Record<string, unknown>;
    assert.equal(data.status, "planned");
    assert.equal(data.targetModel, "google/gemini-3.5-flash");
    assert.deepEqual(data.targetModels, ["google/gemini-3.5-flash"]);
    assert.equal(data.judgeModel, "google/gemini-3-flash-preview");
    assert.equal(data.spendsCredits, false);
    const summary = data.summary as Record<string, unknown>;
    assert.equal(summary.total, 5);
    const estimate = data.estimatedCredits as Record<string, unknown>;
    assert.equal(typeof estimate.totalCredits, "number");
    assert.ok((estimate.totalCredits as number) > 0);
  });

  it("supports comparison dry-run with multiple models", () => {
    const output = runCliWithoutSession([
      "benchmark",
      "model",
      "google/gemini-3.5-flash",
      "google/gemini-3-flash-preview",
      "--compare",
      "--dry-run",
      "--json",
    ]);
    const data = JSON.parse(output) as Record<string, unknown>;
    assert.equal(data.compare, true);
    assert.deepEqual(data.targetModels, ["google/gemini-3.5-flash", "google/gemini-3-flash-preview"]);
    const summary = data.summary as Record<string, unknown>;
    assert.equal(summary.total, 10);
  });

  it("supports selecting one benchmark case by id", () => {
    const output = runCliWithoutSession([
      "benchmark",
      "model",
      "anthropic/claude-haiku-4-5-20251001",
      "--dry-run",
      "--suite",
      "quick",
      "--case",
      "quick-image-brandenburger-tor",
      "--json",
    ]);
    const data = JSON.parse(output) as Record<string, unknown>;
    const summary = data.summary as Record<string, unknown>;
    assert.equal(summary.total, 1);
    assert.equal(summary.skipped, 1);
  });

  it("rejects ambiguous multiple models without compare", () => {
    const result = runCliWithoutSessionResult([
      "benchmark",
      "model",
      "google/gemini-3.5-flash",
      "google/gemini-3-flash-preview",
      "--dry-run",
    ]);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Multiple target models require --compare/);
  });

  it("rejects invalid extensive sizes", () => {
    const result = runCliWithoutSessionResult([
      "benchmark",
      "model",
      "google/gemini-3.5-flash",
      "--dry-run",
      "--suite",
      "extensive",
      "--extensive-size",
      "7",
    ]);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /--extensive-size must be 5, 10, or 20/);
  });

  it("refuses benchmarks when pricing metadata is unavailable", () => {
    const result = runCliWithoutSessionResult([
      "benchmark",
      "model",
      "missing/model",
      "--dry-run",
    ]);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /pricing metadata is unavailable/);
  });

  it("requires explicit spend confirmation for live runs before login checks", () => {
    const result = runCliWithoutSessionResult([
      "benchmark",
      "model",
      "google/gemini-3.5-flash",
    ]);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /--confirm-spend-credits/);
  });
});

function docAssert(claimId: string, assertion: () => void): void {
  try {
    assertion();
  } catch (error) {
    if (error instanceof Error) {
      error.message = `[doc-assert:${claimId}] ${error.message}`;
    }
    throw error;
  }
}

async function runCliAsync(args: string[], env: Record<string, string> = {}): Promise<string> {
  const { stdout } = await execFileAsync("node", ["dist/cli.js", ...args], {
    cwd: PACKAGE_ROOT,
    encoding: "utf-8",
    env: { ...process.env, TERM: "dumb", ...env },
    timeout: 15_000,
  });
  return stdout;
}

async function readJsonBody(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk));
  return JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<string, unknown>;
}

function writeJson(response: ServerResponse, value: unknown): void {
  response.writeHead(200, { "Content-Type": "application/json" });
  response.end(JSON.stringify(value));
}

function writeJsonStatus(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(value));
}

async function withCodeRunMockApi<T>(
  run: (params: { apiUrl: string; requests: Record<string, unknown>[]; getHeaders: () => Record<string, string | string[] | undefined> }) => T | Promise<T>,
): Promise<T> {
  const requests: Record<string, unknown>[] = [];
  let lastHeaders: Record<string, string | string[] | undefined> = {};
  const server = createServer(async (request, response) => {
    try {
      if (request.method === "GET" && request.url === "/raw/main.py") {
        response.writeHead(200, { "Content-Type": "text/plain" });
        response.end("print('url')\n");
        return;
      }
      if (request.method === "POST" && request.url === "/v1/apps/code/skills/run") {
        lastHeaders = request.headers;
        const body = await readJsonBody(request);
        requests.push(body);
        const firstRequest = (body.requests as Array<{ files?: Array<{ path?: string }> }>)[0];
        writeJson(response, {
          success: true,
          data: {
            results: [{
              execution_id: "exec-1",
              status: "queued",
              target_filename: "main.py",
              files: (firstRequest.files ?? []).map((file) => file.path),
              status_path: "/v1/code/run/exec-1",
              stream_path: "/v1/code/run/exec-1/stream",
              credits_per_minute: 5,
            }],
          },
        });
        return;
      }
      if (request.method === "GET" && request.url === "/v1/code/run/exec-1") {
        lastHeaders = request.headers;
        writeJson(response, { status: "finished", exit_code: 0, output: "ok\n" });
        return;
      }
      response.writeHead(404);
      response.end();
    } catch (error) {
      response.writeHead(500, { "Content-Type": "text/plain" });
      response.end(String(error));
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    return await run({ apiUrl: `http://127.0.0.1:${address.port}`, requests, getHeaders: () => lastHeaders });
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
}

async function withAnonymousMockApi<T>(
  run: (params: { apiUrl: string; requests: Record<string, unknown>[]; tempHome: string }) => T | Promise<T>,
): Promise<T> {
  const requests: Record<string, unknown>[] = [];
  const tempHome = join(tmpdir(), `openmates-cli-anonymous-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  mkdirSync(tempHome, { recursive: true });
  const server = createServer(async (request, response) => {
    try {
      if (request.method === "GET" && request.url === "/v1/anonymous/free-usage/status") {
        writeJson(response, {
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
        writeJson(response, {
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
      response.writeHead(404);
      response.end();
    } catch (error) {
      response.writeHead(500, { "Content-Type": "text/plain" });
      response.end(String(error));
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    return await run({ apiUrl: `http://127.0.0.1:${address.port}`, requests, tempHome });
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    rmSync(tempHome, { recursive: true, force: true });
  }
}

async function withEmbedVersionsMockApi<T>(
  run: (params: { apiUrl: string; requests: string[] }) => T | Promise<T>,
): Promise<T> {
  const requests: string[] = [];
  const embedId = "12345678-1234-1234-1234-123456789abc";
  const server = createServer(async (request, response) => {
    requests.push(`${request.method} ${request.url}`);
    if (request.method === "GET" && request.url === `/v1/embeds/${embedId}/versions`) {
      writeJson(response, {
        embed_id: embedId,
        current_version: 3,
        readonly: false,
        versions: [
          { version_number: 1, created_at: 1760000000, has_snapshot: true, has_patch: false },
          { version_number: 2, created_at: 1760000100, has_snapshot: false, has_patch: true },
          { version_number: 3, created_at: 1760000200, has_snapshot: false, has_patch: true },
        ],
      });
      return;
    }
    if (request.method === "GET" && request.url === `/v1/embeds/${embedId}/versions/1`) {
      writeJson(response, {
        embed_id: embedId,
        version_number: 1,
        current_version: 3,
        readonly: false,
        content: "def calculate_average(values):\n    return sum(values) / len(values)",
      });
      return;
    }
    if (request.method === "POST" && request.url === `/v1/embeds/${embedId}/versions/1/restore`) {
      writeJson(response, {
        embed_id: embedId,
        restored_from_version: 1,
        version_number: 4,
        content_hash: "hash-4",
        content: "def calculate_average(values):\n    return sum(values) / len(values)",
      });
      return;
    }
    if (request.method === "POST" && request.url === `/v1/embeds/${embedId}/versions/2/restore`) {
      writeJsonStatus(response, 403, { detail: "Read-only shared history cannot be restored." });
      return;
    }
    response.writeHead(404);
    response.end();
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    return await run({ apiUrl: `http://127.0.0.1:${address.port}`, requests });
  } finally {
    server.close();
  }
}

async function withCodeRunStreamingMockApi<T>(
  run: (params: { apiUrl: string; tempHome: string; getStats: () => { rejected: number; accepted: number } }) => T | Promise<T>,
): Promise<T> {
  const tempHome = join(tmpdir(), `openmates-cli-stream-${Date.now()}`);
  const stateDir = join(tempHome, ".openmates");
  const refreshToken = "raw-refresh-token";
  const stats = { rejected: 0, accepted: 0 };
  mkdirSync(stateDir, { recursive: true });
  const writeSession = (apiUrl: string) => writeFileSync(join(stateDir, "session.json"), `${JSON.stringify({
    apiUrl,
    sessionId: "session-1",
    wsToken: "old-ws-token",
    cookies: { auth_refresh_token: refreshToken },
    masterKeyExportedB64: Buffer.alloc(32).toString("base64"),
    hashedEmail: "hashed-email",
    userEmailSalt: "salt",
    createdAt: Date.now(),
    authorizerDeviceName: "test-device",
    autoLogoutMinutes: null,
  })}\n`);

  const wss = new WebSocketServer({ noServer: true });
  const server = createServer(async (request, response) => {
    try {
      if (request.method === "POST" && request.url === "/v1/auth/session") {
        writeJson(response, { success: true, ws_token: "bad-ws-token" });
        return;
      }
      if (request.method === "POST" && request.url === "/v1/apps/code/skills/run") {
        await readJsonBody(request);
        writeJson(response, {
          success: true,
          data: {
            results: [{
              execution_id: "exec-stream",
              status: "queued",
              target_filename: "hello.py",
              files: ["hello.py"],
              status_path: "/v1/code/run/exec-stream",
              stream_path: "/v1/code/run/exec-stream/stream",
              credits_per_minute: 5,
            }],
          },
        });
        return;
      }
      if (request.method === "GET" && request.url === "/v1/code/run/exec-stream") {
        writeJson(response, { status: "finished", exit_code: 0 });
        return;
      }
      response.writeHead(404);
      response.end();
    } catch (error) {
      response.writeHead(500, { "Content-Type": "text/plain" });
      response.end(String(error));
    }
  });
  server.on("upgrade", (request, socket, head) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    const token = url.searchParams.get("token");
    if (token !== refreshToken) {
      stats.rejected += 1;
      socket.write("HTTP/1.1 403 Forbidden\r\n\r\n");
      socket.destroy();
      return;
    }
    stats.accepted += 1;
    wss.handleUpgrade(request, socket, head, (ws) => {
      setImmediate(() => {
        ws.send(JSON.stringify({ type: "code_run_event", payload: { kind: "stdout", text: "STREAM_FALLBACK_OK\n" } }));
        ws.send(JSON.stringify({ type: "code_run_update", payload: { status: "finished", exit_code: 0 } }));
        setTimeout(() => ws.close(), 10);
      });
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const apiUrl = `http://127.0.0.1:${address.port}`;
  writeSession(apiUrl);
  try {
    return await run({ apiUrl, tempHome, getStats: () => stats });
  } finally {
    wss.close();
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    rmSync(tempHome, { recursive: true, force: true });
  }
}

async function withSkillFormattingMockApi<T>(
  run: (params: { apiUrl: string }) => T | Promise<T>,
): Promise<T> {
  const server = createServer(async (request, response) => {
    try {
      if (request.method === "POST" && request.url === "/v1/apps/events/skills/search") {
        const body = await readJsonBody(request);
        const firstRequest = (body.requests as Array<{ query?: string }> | undefined)?.[0];
        if (firstRequest?.query === "no-match") {
          writeJson(response, {
            success: true,
            data: {
              results: [{
                id: 1,
                results: [],
                no_result_reason: "filtered_out",
                suggestions: ["Relax the date window", "Try a nearby city"],
              }],
              provider: "auto",
              error: null,
            },
            credits_charged: 0,
          });
          return;
        }
        writeJson(response, {
          success: true,
          data: {
            results: [{
              id: 1,
              results: [{
                type: "event_result",
                title: "Accessible Tech Meetup",
                description: "A very long event description that should not dominate default CLI output.",
                provider: "meetup",
                date_start: "2026-06-13T14:00:00+02:00",
                date_end: "2026-06-13T16:00:00+02:00",
                venue: { name: "Community Hall", city: "Berlin" },
                fee: { amount: "0.00", currency: "EUR" },
                constraint_matches: { accessibility: "unknown" },
                hash: "event-hash",
                image_url: "https://example.test/image.jpg",
                url: "https://example.test/event",
              }],
            }],
            provider: "auto",
          },
          credits_charged: 30,
        });
        return;
      }
      if (request.method === "POST" && request.url === "/v1/apps/travel/skills/search_connections") {
        await readJsonBody(request);
        writeJson(response, {
          success: true,
          data: {
            results: [{
              id: 1,
              results: [{
                type: "connection",
                origin: "Berlin (BER)",
                destination: "Barcelona (BCN)",
                departure: "2026-07-10 13:50",
                arrival: "2026-07-10 16:35",
                duration: "2h 45m",
                stops: 0,
                total_price: "192",
                currency: "EUR",
                carriers: ["Vueling"],
                hash: "flight-hash",
                booking_token: "secret-booking-token",
                booking_context: { deep: "provider-context" },
                legs: [{ segments: [{ departure_latitude: 52.36, arrival_latitude: 41.29 }] }],
              }],
            }],
            provider: "Google Flights",
          },
          credits_charged: 25,
        });
        return;
      }
      if (request.method === "POST" && request.url === "/v1/apps/travel/skills/search_stays") {
        await readJsonBody(request);
        writeJson(response, {
          success: true,
          data: {
            results: [{
              id: 1,
              results: [{
                type: "stay",
                name: "Budget Pool Hotel",
                overall_rating: 4.4,
                reviews: 1200,
                rate_per_night: "€172",
                amenities: ["Pool", "Free Wi-Fi"],
                property_token: "secret-property-token",
                images: [{ thumbnail: "https://example.test/thumb.jpg" }],
                nearby_places: [{ name: "Beach" }],
                hash: "stay-hash",
                link: "https://example.test/hotel",
              }],
            }],
            provider: "Google",
          },
          credits_charged: 25,
        });
        return;
      }
      response.writeHead(404);
      response.end();
    } catch (error) {
      response.writeHead(500, { "Content-Type": "text/plain" });
      response.end(String(error));
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    return await run({ apiUrl: `http://127.0.0.1:${address.port}` });
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
}

async function withFlatWeatherSkillMockApi<T>(
  run: (params: { apiUrl: string; requests: Record<string, unknown>[] }) => T | Promise<T>,
): Promise<T> {
  const requests: Record<string, unknown>[] = [];
  const server = createServer(async (request, response) => {
    try {
      if (request.method === "GET" && request.url === "/openapi.json") {
        writeJson(response, {
          paths: {
            "/v1/apps/weather/skills/rain_radar": {
              post: {
                requestBody: {
                  content: {
                    "application/json": {
                      schema: { $ref: "#/components/schemas/RainRadarRequest" },
                    },
                  },
                },
              },
            },
          },
          components: {
            schemas: {
              RainRadarRequest: {
                type: "object",
                properties: {
                  location: { type: "string", description: "German place name for the radar." },
                  radius_km: { type: "integer", default: 5 },
                },
              },
            },
          },
        });
        return;
      }
      if (request.method === "GET" && request.url === "/v1/apps/weather/skills/rain_radar") {
        writeJson(response, {
          id: "rain_radar",
          name: "Rain radar",
          description: "Get nearby German rain radar.",
          providers: [{ provider: "dwd", name: "Deutscher Wetterdienst (DWD)" }],
        });
        return;
      }
      if (request.method === "POST" && request.url === "/v1/apps/weather/skills/rain_radar") {
        const body = await readJsonBody(request);
        requests.push(body);
        if (body.location !== "Berlin") {
          response.writeHead(422, { "Content-Type": "application/json" });
          response.end(JSON.stringify({ detail: "location missing" }));
          return;
        }
        writeJson(response, {
          success: true,
          data: {
            type: "rain_radar",
            provider: "Deutscher Wetterdienst (DWD) via Bright Sky",
            location: { name: "Berlin", country_code: "DE" },
            coverage: { status: "available", radius_km: body.radius_km ?? 5 },
            summary: { in_10_min: "No rain visible near Berlin." },
            timeline: [],
            rendering: { mode: "external_radar_blob", frame_count: 0 },
          },
          credits_charged: 1,
        });
        return;
      }
      response.writeHead(404);
      response.end();
    } catch (error) {
      response.writeHead(500, { "Content-Type": "text/plain" });
      response.end(String(error));
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    return await run({ apiUrl: `http://127.0.0.1:${address.port}`, requests });
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
}

describe("SDK entrypoint", () => {
  it("does not run CLI help when imported", () => {
    const output = execFileSync("node", ["--input-type=module", "-e", "import './dist/index.js';"], {
      cwd: PACKAGE_ROOT,
      encoding: "utf-8",
      env: { ...process.env, TERM: "dumb" },
      timeout: 15_000,
    });

    assert.equal(output, "");
  });
});

describe("assistant response feedback parity", () => {
  it("thanks only for 4-5 star ratings", () => {
    assert.deepEqual(buildAssistantFeedbackDecision(5), {
      rating: 5,
      action: "thanks",
      message: "Thanks for the feedback!",
    });
  });

  it("prompts report issue with the web prefill for 1-3 star ratings", () => {
    assert.deepEqual(buildAssistantFeedbackDecision(3), {
      rating: 3,
      action: "report_issue",
      message: "Thanks for the feedback!",
      reportTitle: "Assistant response quality bad:",
    });
  });

  it("exposes the decision through the CLI command", () => {
    const output = runCliWithoutSession([
      "feedback",
      "assistant-response",
      "--rating",
      "2",
      "--json",
    ]);
    const parsed = JSON.parse(output) as {
      rating: number;
      action: string;
      message: string;
      reportTitle: string;
    };

    assert.equal(parsed.rating, 2);
    assert.equal(parsed.action, "report_issue");
    assert.equal(parsed.message, "Thanks for the feedback!");
    assert.equal(parsed.reportTitle, "Assistant response quality bad:");
  });
});

// ---------------------------------------------------------------------------
// deriveAppUrl
// ---------------------------------------------------------------------------

describe("deriveAppUrl", () => {
  const original = process.env.OPENMATES_APP_URL;
  function reset() {
    if (original === undefined) {
      delete process.env.OPENMATES_APP_URL;
    } else {
      process.env.OPENMATES_APP_URL = original;
    }
  }

  it("maps production API to production web app", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("https://api.openmates.org"),
      "https://openmates.org",
    );
  });

  it("maps dev API to dev web app", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("https://api.dev.openmates.org"),
      "https://app.dev.openmates.org",
    );
  });

  it("maps localhost:8000 to localhost:5173", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("http://localhost:8000"),
      "http://localhost:5173",
    );
  });

  it("maps self-hosted api subdomains to matching app subdomains", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("https://api.custom-instance.example.com"),
      "https://app.custom-instance.example.com",
    );
  });

  it("uses the same origin for self-hosted API URLs without an api subdomain", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("https://openmates.example.com/api"),
      "https://openmates.example.com",
    );
  });

  it("respects OPENMATES_APP_URL env override", () => {
    process.env.OPENMATES_APP_URL = "https://my-custom-app.example.com";
    try {
      assert.strictEqual(
        deriveAppUrl("https://api.openmates.org"),
        "https://my-custom-app.example.com",
      );
    } finally {
      reset();
    }
  });

  it("strips trailing slash from OPENMATES_APP_URL override", () => {
    process.env.OPENMATES_APP_URL = "https://my-custom-app.example.com/";
    try {
      assert.strictEqual(
        deriveAppUrl("https://api.openmates.org"),
        "https://my-custom-app.example.com",
      );
    } finally {
      reset();
    }
  });
});

describe("defaultCloneBranchForVersion", () => {
  it("uses dev for prerelease CLI versions", () => {
    assert.strictEqual(defaultCloneBranchForVersion("0.12.0-alpha.12"), "dev");
    assert.strictEqual(defaultCloneBranchForVersion("0.12.0-beta.1"), "dev");
    assert.strictEqual(defaultCloneBranchForVersion("1.0.0-rc.1"), "dev");
  });

  it("uses the repository default branch for stable CLI versions", () => {
    assert.strictEqual(defaultCloneBranchForVersion("0.11.1"), null);
    assert.strictEqual(defaultCloneBranchForVersion("1.0.0"), null);
  });
});

describe("apps code run command variants", () => {
  it("runs inline code through the canonical app-skill endpoint", async () => {
    await withCodeRunMockApi(async ({ apiUrl, requests, getHeaders }) => {
      const output = await runCliAsync([
        "apps", "code", "run",
        "--api-url", apiUrl,
        "--api-key", "test-key",
        "--json",
        "--language", "python",
        "--filename", "hello.py",
        "--code", "print('hello')\n",
        "--no-internet",
      ]);
      const result = JSON.parse(output) as { execution_id: string; final: { status: string } };
      docAssert("cli-apps-code-run-uses-app-skill-endpoint", () => {
        assert.equal(result.execution_id, "exec-1");
        assert.equal(result.final.status, "finished");
        assert.equal(getHeaders().authorization, "Bearer test-key");
      });
      const body = requests[0] as { requests: Array<{ entry_path: string; enable_internet: boolean; files: Array<{ path: string; language: string; is_target: boolean }> }> };
      assert.equal(body.requests[0].entry_path, "hello.py");
      assert.equal(body.requests[0].enable_internet, false);
      assert.deepEqual(body.requests[0].files.map((file) => [file.path, file.language, file.is_target]), [["hello.py", "python", true]]);
    });
  });

  it("runs repeated --file inputs with an explicit entry", async () => {
    const dir = join(tmpdir(), `openmates-cli-file-${Date.now()}`);
    mkdirSync(dir, { recursive: true });
    try {
      const appFile = join(dir, "app.py");
      const requirementsFile = join(dir, "requirements.txt");
      writeFileSync(appFile, "print('file')\n");
      writeFileSync(requirementsFile, "requests==2.32.3\n");
      await withCodeRunMockApi(async ({ apiUrl, requests }) => {
        await runCliAsync([
          "apps", "code", "run",
          "--api-url", apiUrl,
          "--api-key", "test-key",
          "--json",
          "--entry", "app.py",
          "--file", appFile,
          "--file", requirementsFile,
        ]);
        const body = requests[0] as { requests: Array<{ entry_path: string; files: Array<{ path: string; is_target: boolean }> }> };
        assert.equal(body.requests[0].entry_path, "app.py");
        assert.deepEqual(body.requests[0].files.map((file) => file.path).sort(), ["app.py", "requirements.txt"]);
        assert.equal(body.requests[0].files.find((file) => file.path === "app.py")?.is_target, true);
      });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("runs --dir inputs with excludes", async () => {
    const dir = join(tmpdir(), `openmates-cli-dir-${Date.now()}`);
    mkdirSync(join(dir, "src"), { recursive: true });
    try {
      writeFileSync(join(dir, "main.py"), "print('dir')\n");
      writeFileSync(join(dir, "src", "helper.py"), "VALUE = 1\n");
      writeFileSync(join(dir, "debug.log"), "ignored\n");
      await withCodeRunMockApi(async ({ apiUrl, requests }) => {
        await runCliAsync([
          "apps", "code", "run",
          "--api-url", apiUrl,
          "--api-key", "test-key",
          "--json",
          "--entry", "main.py",
          "--dir", dir,
          "--exclude", "*.log",
        ]);
        const body = requests[0] as { requests: Array<{ files: Array<{ path: string }> }> };
        assert.deepEqual(body.requests[0].files.map((file) => file.path).sort(), ["main.py", "src/helper.py"]);
      });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("runs raw --url inputs after client-side download", async () => {
    await withCodeRunMockApi(async ({ apiUrl, requests }) => {
      await runCliAsync([
        "apps", "code", "run",
        "--api-url", apiUrl,
        "--api-key", "test-key",
        "--json",
        "--entry", "main.py",
        "--url", `${apiUrl}/raw/main.py`,
      ]);
      const body = requests[0] as { requests: Array<{ files: Array<{ path: string; content_base64: string }> }> };
      assert.equal(body.requests[0].files[0].path, "main.py");
      assert.equal(Buffer.from(body.requests[0].files[0].content_base64, "base64").toString("utf8"), "print('url')\n");
    });
  });

  it("runs chat-bound mode without uploading direct files", async () => {
    await withCodeRunMockApi(async ({ apiUrl, requests }) => {
      await runCliAsync([
        "apps", "code", "run",
        "--api-url", apiUrl,
        "--api-key", "test-key",
        "--json",
        "--chat", "chat-1",
        "--target-embed", "embed-1",
      ]);
      const body = requests[0] as { requests: Array<{ mode: string; chat_id: string; target_embed_id: string; files: unknown[] }> };
      assert.equal(body.requests[0].mode, "chat_bound");
      assert.equal(body.requests[0].chat_id, "chat-1");
      assert.equal(body.requests[0].target_embed_id, "embed-1");
      assert.deepEqual(body.requests[0].files, []);
    });
  });

  it("retries Code Run streaming with the refresh token when ws_token auth is rejected", async () => {
    await withCodeRunStreamingMockApi(async ({ apiUrl, tempHome, getStats }) => {
      await runCliAsync([
        "apps", "code", "run",
        "--api-url", apiUrl,
        "--language", "python",
        "--filename", "hello.py",
        "--code", "print('hello')\n",
      ], { HOME: tempHome });
      assert.deepEqual(getStats(), { rejected: 1, accepted: 1 });
    });
  });
});

describe("embed version commands", () => {
  const embedId = "12345678-1234-1234-1234-123456789abc";

  it("lists embed versions without encrypted blobs", async () => {
    await withEmbedVersionsMockApi(async ({ apiUrl, requests }) => {
      const output = await runCliAsync(["embeds", "versions", "list", embedId], { OPENMATES_API_URL: apiUrl });
      assert.match(output, /Embed versions/);
      assert.match(output, /v1/);
      assert.match(output, /v3 \(current\)/);
      assert.doesNotMatch(output, /encrypted_/);
      assert.deepEqual(requests, [`GET /v1/embeds/${embedId}/versions`]);
    });
  });

  it("shows a reconstructed historical version", async () => {
    await withEmbedVersionsMockApi(async ({ apiUrl, requests }) => {
      const output = await runCliAsync(["embeds", "versions", "show", embedId, "--version", "1"], { OPENMATES_API_URL: apiUrl });
      assert.match(output, /def calculate_average/);
      assert.deepEqual(requests, [`GET /v1/embeds/${embedId}/versions/1`]);
    });
  });

  it("writes a reconstructed historical version to a file", async () => {
    const tempFile = join(tmpdir(), `openmates-embed-version-${Date.now()}.py`);
    await withEmbedVersionsMockApi(async ({ apiUrl, requests }) => {
      const output = await runCliAsync(["embeds", "versions", "show", embedId, "--version", "1", "--output", tempFile], { OPENMATES_API_URL: apiUrl });
      assert.match(output, /Wrote .* v1/);
      assert.match(readFileSync(tempFile, "utf-8"), /def calculate_average/);
      assert.deepEqual(requests, [`GET /v1/embeds/${embedId}/versions/1`]);
    });
    rmSync(tempFile, { force: true });
  });

  it("requires local encrypted cache for client-side restore before any server restore endpoint", async () => {
    await withEmbedVersionsMockApi(async ({ apiUrl, requests }) => {
      const { stderr } = await runCliWithEmptyCacheSession(apiUrl, ["embeds", "versions", "restore", embedId, "--version", "1", "--yes"]);
      assert.match(stderr, /not found in local cache/);
      assert.deepEqual(requests.filter((request) => request !== "POST /v1/auth/session"), []);
    });
  });

  it("does not attempt plaintext server restore for any version", async () => {
    await withEmbedVersionsMockApi(async ({ apiUrl, requests }) => {
      const { stderr } = await runCliWithEmptyCacheSession(apiUrl, ["embeds", "versions", "restore", embedId, "--version", "2", "--yes"]);
      assert.match(stderr, /not found in local cache/);
      assert.deepEqual(requests.filter((request) => request !== "POST /v1/auth/session"), []);
    });
  });
});

describe("apps skill formatted output", () => {
  it("maps flat weather rain radar schemas to direct CLI app-skill input", async () => {
    await withFlatWeatherSkillMockApi(async ({ apiUrl, requests }) => {
      const inlineOutput = await runCliAsync([
        "--api-url", apiUrl,
        "apps", "weather", "rain_radar", "Berlin",
        "--json",
      ]);
      const inlineResult = JSON.parse(inlineOutput) as { data: { type: string } };
      assert.equal(inlineResult.data.type, "rain_radar");
      assert.deepEqual(requests[0], { location: "Berlin" });

      await runCliAsync([
        "--api-url", apiUrl,
        "apps", "weather", "rain_radar",
        "--input", JSON.stringify({ requests: [{ location: "Berlin", radius_km: 10 }] }),
        "--json",
      ]);
      assert.deepEqual(requests[1], { location: "Berlin", radius_km: 10 });
    });
  });

  it("prints flat weather rain radar help without a requests wrapper", async () => {
    await withFlatWeatherSkillMockApi(async ({ apiUrl }) => {
      const output = await runCliAsync([
        "--api-url", apiUrl,
        "apps", "weather", "rain_radar", "--help",
      ]);
      assert.match(output, /"location": "Berlin, Germany"/);
      assert.doesNotMatch(output, /"requests"/);
    });
  });

  it("prints concise event cards without raw provider noise by default", async () => {
    await withSkillFormattingMockApi(async ({ apiUrl }) => {
      const output = await runCliAsync([
        "--api-url", apiUrl,
        "apps", "events", "search",
        "--input", JSON.stringify({ requests: [{ query: "tech", location: "Berlin" }] }),
      ]);

      assert.match(output, /Accessible Tech Meetup/);
      assert.match(output, /2026-06-13T14:00:00\+02:00/);
      assert.match(output, /Community Hall/);
      assert.match(output, /accessibility/);
      assert.match(output, /unknown/);
      assert.doesNotMatch(output, /event-hash/);
      assert.doesNotMatch(output, /image_url/);
      assert.doesNotMatch(output, /very long event description/);
    });
  });

  it("prints concise connection cards without booking internals by default", async () => {
    await withSkillFormattingMockApi(async ({ apiUrl }) => {
      const output = await runCliAsync([
        "--api-url", apiUrl,
        "apps", "travel", "search_connections",
        "--input", JSON.stringify({ requests: [{ legs: [{ origin: "Berlin", destination: "Barcelona", date: "2026-07-10" }] }] }),
      ]);

      assert.match(output, /Berlin \(BER\) → Barcelona \(BCN\)/);
      assert.match(output, /192 EUR · direct · Vueling/);
      assert.match(output, /Get booking URL/);
      assert.doesNotMatch(output, /secret-booking-token/);
      assert.doesNotMatch(output, /booking_context/);
      assert.doesNotMatch(output, /departure_latitude/);
      assert.doesNotMatch(output, /flight-hash/);
    });
  });

  it("prints concise stay cards without property internals by default", async () => {
    await withSkillFormattingMockApi(async ({ apiUrl }) => {
      const output = await runCliAsync([
        "--api-url", apiUrl,
        "apps", "travel", "search_stays",
        "--input", JSON.stringify({ requests: [{ query: "Hotels in Barcelona", check_in_date: "2026-07-10", check_out_date: "2026-07-13" }] }),
      ]);

      assert.match(output, /Budget Pool Hotel/);
      assert.match(output, /★ 4.4/);
      assert.match(output, /€172/);
      assert.match(output, /Pool/);
      assert.doesNotMatch(output, /secret-property-token/);
      assert.doesNotMatch(output, /property_token/);
      assert.doesNotMatch(output, /images/);
      assert.doesNotMatch(output, /nearby_places/);
      assert.doesNotMatch(output, /stay-hash/);
    });
  });

  it("prints clear no-result reasons and suggestions", async () => {
    await withSkillFormattingMockApi(async ({ apiUrl }) => {
      const output = await runCliAsync([
        "--api-url", apiUrl,
        "apps", "events", "search",
        "--input", JSON.stringify({ requests: [{ query: "no-match", location: "Berlin" }] }),
      ]);

      assert.match(output, /No results found/i);
      assert.match(output, /filtered_out/);
      assert.match(output, /Relax the date window/);
      assert.match(output, /Try a nearby city/);
      assert.doesNotMatch(output, /\{\s*"results"/);
    });
  });
});

// ---------------------------------------------------------------------------
// MEMORY_TYPE_REGISTRY
// ---------------------------------------------------------------------------

describe("MEMORY_TYPE_REGISTRY", () => {
  it("contains at least 10 memory types", () => {
    const keys = Object.keys(MEMORY_TYPE_REGISTRY);
    docAssert("cli-apps-memory-type-registry-is-available", () => {
      assert.ok(keys.length >= 10, `expected >=10 types, got ${keys.length}`);
    });
  });

  it("every type has appId, itemType, required, and properties", () => {
    for (const [key, def] of Object.entries(MEMORY_TYPE_REGISTRY)) {
      assert.ok(def.appId, `${key}: missing appId`);
      assert.ok(def.itemType, `${key}: missing itemType`);
      assert.ok(
        Array.isArray(def.required),
        `${key}: required should be array`,
      );
      assert.ok(
        typeof def.properties === "object",
        `${key}: properties should be object`,
      );
    }
  });

  it("all required fields are present in properties", () => {
    for (const [key, def] of Object.entries(MEMORY_TYPE_REGISTRY)) {
      for (const req of def.required) {
        assert.ok(
          def.properties[req] !== undefined,
          `${key}: required field '${req}' missing from properties`,
        );
      }
    }
  });

  it("code/preferred_tech requires 'name'", () => {
    const def = MEMORY_TYPE_REGISTRY["code/preferred_tech"];
    assert.ok(def, "code/preferred_tech should exist");
    assert.ok(def.required.includes("name"), "should require 'name'");
  });

  it("ai/communication_style has enum values for 'tone'", () => {
    const def = MEMORY_TYPE_REGISTRY["ai/communication_style"];
    assert.ok(def, "ai/communication_style should exist");
    const tone = def.properties["tone"];
    assert.ok(
      tone?.enum && tone.enum.length > 0,
      "tone should have enum values",
    );
    assert.ok(
      tone.enum!.includes("formal"),
      "tone enum should include 'formal'",
    );
  });

  it("registry key format matches appId/itemType", () => {
    for (const [key, def] of Object.entries(MEMORY_TYPE_REGISTRY)) {
      const expectedKey = `${def.appId}/${def.itemType}`;
      assert.strictEqual(
        key,
        expectedKey,
        `key mismatch: ${key} vs ${expectedKey}`,
      );
    }
  });
});

// ---------------------------------------------------------------------------
// Schema validation (via OpenMatesClient.createMemory validation path)
// In isolation: we test the validation logic that would be called by the client.
// We re-implement a minimal version to keep tests network-free.
// ---------------------------------------------------------------------------

function validateMemory(
  registryKey: string,
  itemValue: Record<string, unknown>,
): { valid: true } | { valid: false; error: string } {
  const schema = MEMORY_TYPE_REGISTRY[registryKey];
  if (!schema) {
    return { valid: false, error: `Unknown type: ${registryKey}` };
  }
  const missing = schema.required.filter(
    (f) =>
      itemValue[f] === undefined ||
      itemValue[f] === null ||
      itemValue[f] === "",
  );
  if (missing.length > 0) {
    return { valid: false, error: `Missing required: ${missing.join(", ")}` };
  }
  for (const [field, def] of Object.entries(schema.properties)) {
    const val = itemValue[field];
    if (val !== undefined && def.enum && !def.enum.includes(String(val))) {
      return {
        valid: false,
        error: `Invalid enum value '${String(val)}' for '${field}'`,
      };
    }
  }
  return { valid: true };
}

describe("memory schema validation", () => {
  it("accepts valid code/preferred_tech entry", () => {
    const result = validateMemory("code/preferred_tech", {
      name: "Python",
      proficiency: "advanced",
    });
    assert.ok(result.valid);
  });

  it("rejects missing required field", () => {
    const result = validateMemory("code/preferred_tech", {
      proficiency: "advanced",
    });
    assert.ok(!result.valid);
    assert.ok(result.valid === false && result.error.includes("name"));
  });

  it("rejects invalid enum value", () => {
    const result = validateMemory("code/preferred_tech", {
      name: "Python",
      proficiency: "guru",
    });
    assert.ok(!result.valid);
    assert.ok(result.valid === false && result.error.includes("guru"));
  });

  it("accepts valid ai/communication_style entry", () => {
    const result = validateMemory("ai/communication_style", {
      title: "Work Mode",
      tone: "professional",
      verbosity: "detailed",
    });
    assert.ok(result.valid);
  });

  it("rejects unknown memory type", () => {
    const result = validateMemory("fake/nonexistent", { name: "x" });
    assert.ok(!result.valid);
    assert.ok(result.valid === false && result.error.includes("Unknown"));
  });

  it("accepts entry with optional fields omitted", () => {
    const result = validateMemory("books/favorite_books", { title: "Dune" });
    assert.ok(result.valid);
  });
});

// ---------------------------------------------------------------------------
// Follow-up suggestions rendering helpers (network-free)
// ---------------------------------------------------------------------------

/**
 * Simulate the terminal output format for follow-up suggestions.
 * Mirrors the rendering logic in sendMessageStreaming() and printChatConversation()
 * in cli.ts without requiring a live network connection.
 */
function renderFollowUpSuggestions(
  shortChatId: string,
  suggestions: string[],
): string {
  if (suggestions.length === 0) return "";
  let out = "Suggested follow-ups:\n";
  for (const suggestion of suggestions) {
    const escaped = suggestion.replace(/"/g, '\\"');
    out += `  • ${suggestion}\n`;
    out += `    openmates chats send --chat ${shortChatId} "${escaped}"\n`;
  }
  return out;
}

describe("follow-up suggestions rendering", () => {
  it("renders a list of follow-up suggestions with send commands", () => {
    const output = renderFollowUpSuggestions("d262cb68", [
      "What are the main benefits?",
      "Can you give me an example?",
    ]);
    assert.ok(output.includes("Suggested follow-ups:"));
    assert.ok(output.includes("• What are the main benefits?"));
    assert.ok(
      output.includes(
        'openmates chats send --chat d262cb68 "What are the main benefits?"',
      ),
    );
    assert.ok(output.includes("• Can you give me an example?"));
    assert.ok(
      output.includes(
        'openmates chats send --chat d262cb68 "Can you give me an example?"',
      ),
    );
  });

  it("renders nothing for empty suggestions list", () => {
    const output = renderFollowUpSuggestions("d262cb68", []);
    assert.strictEqual(output, "");
  });

  it("escapes double quotes inside suggestion text for shell safety", () => {
    const output = renderFollowUpSuggestions("a1b2c3d4", [
      'What is "machine learning"?',
    ]);
    assert.ok(
      output.includes(
        `openmates chats send --chat a1b2c3d4 "What is \\"machine learning\\"?"`,
      ),
    );
  });
});

// ---------------------------------------------------------------------------
// New chat suggestions rendering helpers (network-free)
// ---------------------------------------------------------------------------

/**
 * Simulate new-chat suggestion rendering.
 * Mirrors printNewChatSuggestion() in cli.ts without network.
 */
function renderNewChatSuggestion(
  suggestion: { body: string },
  index: number,
): string {
  const escaped = suggestion.body.replace(/"/g, '\\"');
  return (
    `${index}. ${suggestion.body}\n` +
    `   openmates chats new "${escaped}"\n`
  );
}

describe("new chat suggestions rendering", () => {
  it("renders a plain suggestion without app or skill labels", () => {
    const output = renderNewChatSuggestion({ body: "Find upcoming drawing workshops in Berlin" }, 1);
    assert.ok(output.startsWith("1. Find upcoming drawing workshops"));
    assert.ok(
      output.includes(
        'openmates chats new "Find upcoming drawing workshops in Berlin"',
      ),
    );
  });

  it("renders legacy-prefixed suggestions as already-stripped plain text", () => {
    const output = renderNewChatSuggestion({ body: "Find current AI news" }, 2);
    assert.ok(output.startsWith("2. Find current AI news"));
    assert.ok(!output.includes("[web-search]"));
  });

  it("correctly numbers multiple suggestions", () => {
    const suggestions = [
      "Search current AI trends",
      "Find startup funding news",
      "Explain how to improve sleep",
    ];
    const outputs = suggestions.map((body, i) => renderNewChatSuggestion({ body }, i + 1));
    assert.ok(outputs[0].startsWith("1."));
    assert.ok(outputs[1].startsWith("2."));
    assert.ok(outputs[2].startsWith("3."));
  });

  it("escapes double quotes in suggestion body for shell safety", () => {
    const output = renderNewChatSuggestion({ body: 'Summarize the book "Thinking Fast and Slow"' }, 1);
    assert.ok(
      output.includes(
        'openmates chats new "Summarize the book \\"Thinking Fast and Slow\\""',
      ),
    );
  });
});

// ---------------------------------------------------------------------------
// --followup flag: suggestion resolution helpers (network-free)
// ---------------------------------------------------------------------------

/**
 * Simulate the --followup <n> resolution logic from the `chats send` handler.
 * Returns the selected suggestion text or an error string.
 * Mirrors the logic in handleChats() send branch in cli.ts.
 */
function resolveFollowUp(
  suggestions: string[],
  n: number,
): { ok: true; message: string } | { ok: false; error: string } {
  if (suggestions.length === 0) {
    return { ok: false, error: "no_suggestions" };
  }
  if (isNaN(n) || n < 1) {
    return { ok: false, error: "invalid_n" };
  }
  if (n > suggestions.length) {
    return {
      ok: false,
      error: `out_of_range:${suggestions.length}`,
    };
  }
  return { ok: true, message: suggestions[n - 1] };
}

describe("--followup flag resolution", () => {
  const SUGGESTIONS = [
    "What are the main trade-offs?",
    "Can you show a code example?",
    "How does this compare to alternatives?",
    "What are common pitfalls to avoid?",
    "Is there a simpler approach?",
    "What documentation should I read next?",
  ];

  it("resolves --followup 1 to the first suggestion", () => {
    const result = resolveFollowUp(SUGGESTIONS, 1);
    assert.ok(result.ok);
    assert.strictEqual(
      result.ok && result.message,
      "What are the main trade-offs?",
    );
  });

  it("resolves --followup 3 to the third suggestion", () => {
    const result = resolveFollowUp(SUGGESTIONS, 3);
    assert.ok(result.ok);
    assert.strictEqual(
      result.ok && result.message,
      "How does this compare to alternatives?",
    );
  });

  it("resolves --followup 6 to the last suggestion (boundary)", () => {
    const result = resolveFollowUp(SUGGESTIONS, 6);
    assert.ok(result.ok);
    assert.strictEqual(
      result.ok && result.message,
      "What documentation should I read next?",
    );
  });

  it("returns error when n is out of range (too high)", () => {
    const result = resolveFollowUp(SUGGESTIONS, 7);
    assert.ok(!result.ok);
    assert.ok(!result.ok && result.error.startsWith("out_of_range:"));
    // Error message includes the actual count for user feedback
    assert.ok(!result.ok && result.error.includes(String(SUGGESTIONS.length)));
  });

  it("returns error for n=0 (invalid — 1-based index)", () => {
    const result = resolveFollowUp(SUGGESTIONS, 0);
    assert.ok(!result.ok);
    assert.strictEqual(!result.ok && result.error, "invalid_n");
  });

  it("returns error for negative n", () => {
    const result = resolveFollowUp(SUGGESTIONS, -1);
    assert.ok(!result.ok);
    assert.strictEqual(!result.ok && result.error, "invalid_n");
  });

  it("returns error when suggestions list is empty", () => {
    const result = resolveFollowUp([], 1);
    assert.ok(!result.ok);
    assert.strictEqual(!result.ok && result.error, "no_suggestions");
  });

  it("resolves a suggestion with quotes correctly (shell safety check)", () => {
    const withQuotes = [
      'Explain "zero-knowledge proofs" in plain English',
      "What is a practical use case?",
    ];
    const result = resolveFollowUp(withQuotes, 1);
    assert.ok(result.ok);
    // The message contains quotes — callers must escape before embedding in shell commands
    assert.ok(result.ok && result.message.includes('"zero-knowledge proofs"'));
  });

  it("is 1-based: --followup 1 is index 0, --followup 2 is index 1", () => {
    const result1 = resolveFollowUp(SUGGESTIONS, 1);
    const result2 = resolveFollowUp(SUGGESTIONS, 2);
    assert.ok(result1.ok && result2.ok);
    assert.notStrictEqual(
      result1.ok && result1.message,
      result2.ok && result2.message,
    );
    assert.strictEqual(result1.ok && result1.message, SUGGESTIONS[0]);
    assert.strictEqual(result2.ok && result2.message, SUGGESTIONS[1]);
  });
});

// ---------------------------------------------------------------------------
// serializeToYaml
// ---------------------------------------------------------------------------

describe("serializeToYaml", () => {
  it("serializes simple key-value pairs", () => {
    const result = serializeToYaml({ name: "Alice", age: 30 });
    assert.ok(result.includes("name: Alice"));
    assert.ok(result.includes("age: 30"));
  });

  it("serializes null values", () => {
    const result = serializeToYaml({ title: null });
    assert.ok(result.includes("title: null"));
  });

  it("serializes boolean values", () => {
    const result = serializeToYaml({ active: true, deleted: false });
    assert.ok(result.includes("active: true"));
    assert.ok(result.includes("deleted: false"));
  });

  it("serializes multiline strings with block scalar", () => {
    const result = serializeToYaml({ content: "line one\nline two\nline three" });
    assert.ok(result.includes("content: |"));
    assert.ok(result.includes("  line one"));
    assert.ok(result.includes("  line two"));
  });

  it("quotes strings containing colons", () => {
    const result = serializeToYaml({ url: "https://example.com" });
    assert.ok(result.includes('"https://example.com"'));
  });

  it("quotes strings containing hash marks", () => {
    const result = serializeToYaml({ comment: "color #ff0000" });
    assert.ok(result.includes('"color #ff0000"'));
  });

  it("quotes strings that look like YAML booleans", () => {
    const result = serializeToYaml({ value: "true" });
    assert.ok(result.includes('"true"'));
  });

  it("quotes empty strings", () => {
    const result = serializeToYaml({ empty: "" });
    assert.ok(result.includes('empty: ""'));
  });

  it("serializes nested objects", () => {
    const result = serializeToYaml({ chat: { title: "Hello", count: 5 } });
    assert.ok(result.includes("chat:"));
    assert.ok(result.includes("  title: Hello"));
    assert.ok(result.includes("  count: 5"));
  });

  it("serializes arrays of primitives", () => {
    const result = serializeToYaml({ tags: ["a", "b", "c"] });
    assert.ok(result.includes("tags:"));
    assert.ok(result.includes("- a"));
    assert.ok(result.includes("- b"));
  });

  it("serializes arrays of objects", () => {
    const result = serializeToYaml({
      messages: [
        { role: "user", content: "hi" },
        { role: "assistant", content: "hello" },
      ],
    });
    assert.ok(result.includes("messages:"));
    assert.ok(result.includes("role: user"));
    assert.ok(result.includes("role: assistant"));
    assert.ok(result.includes("content: hi"));
    assert.ok(result.includes("content: hello"));
  });

  it("preserves double quotes in unquoted strings", () => {
    const result = serializeToYaml({ note: 'say "hello"' });
    assert.ok(result.includes('note: say "hello"'));
  });

  it("handles deeply nested structures", () => {
    const result = serializeToYaml({
      a: { b: { c: { d: "deep" } } },
    });
    assert.ok(result.includes("      d: deep"));
  });

  it("produces consistent output matching web app YAML format", () => {
    const result = serializeToYaml({
      chat: {
        title: "Test Chat",
        exported_at: "2026-03-21T10:00:00.000Z",
        message_count: 2,
        summary: null,
      },
      messages: [
        {
          role: "user",
          sender: "You",
          model: null,
          timestamp: "2026-03-21T10:00:00.000Z",
          content: "Hello",
        },
      ],
    });
    // Verify structure matches expected chat export format
    assert.ok(result.includes("chat:"));
    assert.ok(result.includes("  title: Test Chat"));
    assert.ok(result.includes("  message_count: 2"));
    assert.ok(result.includes("  summary: null"));
    assert.ok(result.includes("messages:"));
    assert.ok(result.includes("    role: user"));
    assert.ok(result.includes("    sender: You"));
    assert.ok(result.includes("    content: Hello"));
  });
});

// ---------------------------------------------------------------------------
// getExtForLang
// ---------------------------------------------------------------------------

describe("getExtForLang", () => {
  it("maps common languages to correct extensions", () => {
    assert.strictEqual(getExtForLang("javascript"), "js");
    assert.strictEqual(getExtForLang("typescript"), "ts");
    assert.strictEqual(getExtForLang("python"), "py");
    assert.strictEqual(getExtForLang("ruby"), "rb");
    assert.strictEqual(getExtForLang("rust"), "rs");
    assert.strictEqual(getExtForLang("golang"), "go");
    assert.strictEqual(getExtForLang("go"), "go");
    assert.strictEqual(getExtForLang("java"), "java");
    assert.strictEqual(getExtForLang("csharp"), "cs");
    assert.strictEqual(getExtForLang("cpp"), "cpp");
  });

  it("maps web languages correctly", () => {
    assert.strictEqual(getExtForLang("html"), "html");
    assert.strictEqual(getExtForLang("css"), "css");
    assert.strictEqual(getExtForLang("scss"), "scss");
    assert.strictEqual(getExtForLang("json"), "json");
    assert.strictEqual(getExtForLang("yaml"), "yml");
    assert.strictEqual(getExtForLang("xml"), "xml");
  });

  it("maps shell and config languages correctly", () => {
    assert.strictEqual(getExtForLang("shell"), "sh");
    assert.strictEqual(getExtForLang("bash"), "sh");
    assert.strictEqual(getExtForLang("powershell"), "ps1");
    assert.strictEqual(getExtForLang("dockerfile"), "Dockerfile");
    assert.strictEqual(getExtForLang("toml"), "toml");
    assert.strictEqual(getExtForLang("sql"), "sql");
  });

  it("maps Svelte/React frameworks correctly", () => {
    assert.strictEqual(getExtForLang("svelte"), "svelte");
    assert.strictEqual(getExtForLang("vue"), "vue");
    assert.strictEqual(getExtForLang("jsx"), "jsx");
    assert.strictEqual(getExtForLang("tsx"), "tsx");
  });

  it("is case-insensitive", () => {
    assert.strictEqual(getExtForLang("JavaScript"), "js");
    assert.strictEqual(getExtForLang("PYTHON"), "py");
    assert.strictEqual(getExtForLang("TypeScript"), "ts");
  });

  it("falls back to lowercased language name for unknown languages", () => {
    assert.strictEqual(getExtForLang("zig"), "zig");
    assert.strictEqual(getExtForLang("haskell"), "haskell");
    assert.strictEqual(getExtForLang("ELIXIR"), "elixir");
  });

  it("returns 'txt' for empty string", () => {
    assert.strictEqual(getExtForLang(""), "txt");
  });
});

// ---------------------------------------------------------------------------
// CLI command help and local-only behavior
// ---------------------------------------------------------------------------

describe("settings command surface", () => {
  it("lists predefined settings commands instead of raw passthrough", () => {
    const output = runCli(["settings", "--help"]);
    docAssert("cli-settings-lists-predefined-commands", () => {
      assert.ok(output.includes("Predefined commands only"));
      assert.ok(output.includes("openmates settings account timezone set"));
      assert.ok(output.includes("openmates settings billing gift-card redeem"));
      assert.ok(!output.includes("settings get <path>"));
      assert.ok(!output.includes("settings post <path>"));
    });
  });

  it("shows nested help examples for settings groups", () => {
    const output = runCli(["settings", "billing", "--help"]);
    assert.ok(output.includes("openmates settings billing overview"));
    assert.ok(output.includes("e.g. openmates settings billing usage"));
    assert.ok(output.includes("buy-credits bank-transfer"));
    assert.ok(output.includes("gift-card redeem"));
    assert.ok(output.includes("gift-card buy bank-transfer"));
    assert.ok(output.includes("invoices download"));
  });

  it("shows executable help for profile, notifications, mates, and newsletter", () => {
    assert.ok(runCli(["settings", "account", "profile-picture", "--help"]).includes("profile-picture set"));
    assert.ok(runCli(["settings", "notifications", "--help"]).includes("notifications email set"));
    assert.ok(runCli(["settings", "--help"]).includes("notifications list"));
    assert.ok(runCli(["settings", "--help"]).includes("notifications stream"));
    assert.ok(runCli(["settings", "mates", "--help"]).includes("mates list"));
    assert.ok(runCli(["settings", "newsletter", "--help"]).includes("newsletter subscribe"));
  });

  it("rejects raw settings passthrough before auth or network", () => {
    docAssert("cli-settings-rejects-raw-passthrough", () => {
      assert.throws(
        () => runCli(["settings", "get", "billing"]),
        /Raw settings passthrough is no longer supported/,
      );
    });
  });

  it("rejects account deletion verification codes passed as flags", () => {
    assert.throws(
      () => runCli(["settings", "account", "delete", "--email-code", "123456"]),
      /verification codes must be entered through interactive prompts/,
    );
  });

  it("prints web-only help for security sessions", () => {
    const output = runCli(["settings", "security", "sessions"]);
    assert.ok(output.includes("Session management is web-only"));
    assert.ok(output.includes("#settings/account/security/sessions"));
  });

  it("lists mates without auth or network", () => {
    const output = runCli(["settings", "mates", "list", "--json"]);
    const parsed = JSON.parse(output) as Array<{ id: string; mention: string }>;
    assert.ok(parsed.some((mate) => mate.id === "software_development"));
    assert.ok(parsed.some((mate) => mate.mention === "@mate:general_knowledge"));
  });
});

describe("incognito command surface", () => {
  it("does not expose stored incognito history", () => {
    const output = runCli(["chats", "incognito-history"]);
    assert.ok(output.includes("Incognito chats are not stored"));
  });

  it("returns empty unstored incognito history in JSON mode", () => {
    const output = runCli(["chats", "incognito-history", "--json"]);
    const parsed = JSON.parse(output);
    assert.deepEqual(parsed.history, []);
    assert.strictEqual(parsed.stored, false);
  });
});

describe("unauthenticated example chats", () => {
  it("lists public example chats without a session", () => {
    const output = runCliWithoutSession(["chats", "list", "--json"]);
    const parsed = JSON.parse(output) as { chats: Array<{ source?: string; title?: string; id?: string }> };
    assert.ok(parsed.chats.length > 0);
    assert.ok(parsed.chats.every((chat) => chat.source === "example"));
    assert.ok(parsed.chats.some((chat) => chat.id === "example-gigantic-airplanes"));
  });

  it("labels example chats in human list output", () => {
    const output = runCliWithoutSession(["chats", "list", "--limit", "1"]);
    assert.ok(output.includes("Example chats"));
    assert.ok(output.includes("EXAMPLE CHAT"));
  });

  it("shows an example chat with an explicit example banner", () => {
    const output = runCliWithoutSession(["chats", "show", "example-gigantic-airplanes"]);
    assert.ok(output.includes("EXAMPLE CHAT"));
    assert.ok(output.includes("Gigantic airplanes for transporting rocket and airplane parts"));
    assert.ok(output.includes("This is a public example chat"));
  });

  it("returns signup_required before reading anonymous file references", () => {
    const result = runCliWithoutSessionResult([
      "chats",
      "new",
      "summarize @/tmp/openmates-anonymous-file-that-must-not-be-read.txt",
      "--json",
    ]);
    assert.equal(result.status, 0, result.stderr);
    const parsed = JSON.parse(result.stdout) as { status?: string; reason?: string; signup_required?: boolean };
    assert.equal(parsed.status, "signup_required");
    assert.equal(parsed.reason, "file_upload_requires_signup");
    assert.equal(parsed.signup_required, true);
  });

  it("sends anonymous text chat through the anonymous API without a session", async () => {
    await withAnonymousMockApi(async ({ apiUrl, requests, tempHome }) => {
      const output = await runCliAsync(
        ["chats", "new", "Reply with exactly: anonymous inference ok", "--json", "--api-url", apiUrl],
        { HOME: tempHome, USERPROFILE: tempHome },
      );
      const parsed = JSON.parse(output) as { status?: string; assistant?: string };
      assert.equal(parsed.status, "completed");
      assert.equal(parsed.assistant, "anonymous inference ok");
      assert.equal(requests.length, 1);
      assert.equal(requests[0].plaintext_message, "Reply with exactly: anonymous inference ok");
      assert.equal(typeof requests[0].anonymous_id, "string");
    });
  });

  it("redacts PII in anonymous chat by default", async () => {
    await withAnonymousMockApi(async ({ apiUrl, requests, tempHome }) => {
      await runCliAsync(
        [
          "chats",
          "new",
          "Email sarah@example.com or call +1 (555) 123-4567.",
          "--json",
          "--api-url",
          apiUrl,
        ],
        { HOME: tempHome, USERPROFILE: tempHome },
      );

      assert.equal(requests.length, 1);
      assert.equal(
        requests[0].plaintext_message,
        "Email [EMAIL_1_com] or call [PHONE_1_567].",
      );
    });
  });

  it("keeps raw PII when anonymous chat opts out", async () => {
    await withAnonymousMockApi(async ({ apiUrl, requests, tempHome }) => {
      await runCliAsync(
        [
          "chats",
          "new",
          "Email sarah@example.com or call +1 (555) 123-4567.",
          "--json",
          "--api-url",
          apiUrl,
          "--no-pii-detection",
        ],
        { HOME: tempHome, USERPROFILE: tempHome },
      );

      assert.equal(requests.length, 1);
      assert.equal(
        requests[0].plaintext_message,
        "Email sarah@example.com or call +1 (555) 123-4567.",
      );
    });
  });
});

describe("documented CLI command reference", () => {
  it("top-level help lists the user guide command categories", () => {
    const output = runCli(["--help"]);
    const doc = readRepoText("docs/user-guide/cli/README.md");
    docAssert("cli-readme-lists-command-categories", () => {
      for (const command of [
        "login",
        "signup",
        "logout",
        "whoami",
        "chats",
        "apps",
        "settings",
        "benchmark",
        "embeds",
        "mentions",
        "inspirations",
        "newchatsuggestions",
        "server",
        "docs",
      ]) {
        assert.ok(output.includes(command), `expected top-level help to mention ${command}`);
        assert.ok(doc.includes(command), `expected user guide overview to mention ${command}`);
      }
      assert.ok(!doc.includes("e2e provision-auth-accounts"));
    });
    docAssert("cli-authentication-uses-pair-login-command", () => {
      assert.ok(output.includes("login"));
      assert.ok(!output.includes("password"));
    });
  });

  it("npm README onboarding matches the current command surface", () => {
    const readme = readRepoText("frontend/packages/openmates-cli/README.md");
    const help = runCli(["--help"]);
    docAssert("cli-npm-readme-onboarding-matches-command-surface", () => {
      for (const command of ["login", "signup", "chats", "apps", "settings", "benchmark", "server", "docs"]) {
        assert.ok(help.includes(command), `expected help to mention ${command}`);
        assert.ok(readme.includes(`openmates ${command}`), `expected README to include openmates ${command}`);
      }
      assert.ok(readme.includes("openmates apps code run"));
      assert.ok(readme.includes("openmates settings account export data --json"));
      assert.ok(readme.includes("Predefined settings commands"));
      assert.ok(!readme.includes("settings get /v1/settings"));
      assert.ok(!readme.includes("BLOCKED_SETTINGS_POST_PATHS"));
      assert.ok(readme.includes("BLOCKED_SETTINGS_MUTATE_PATHS"));
    });
  });

  it("benchmark docs cover benchmark help options", () => {
    const doc = readRepoText("docs/user-guide/cli/benchmarks.md");
    const help = runCli(["benchmark", "--help"]);
    docAssert("cli-benchmark-docs-cover-help", () => {
      for (const fragment of [
        "benchmark model <provider/model>",
        "--confirm-spend-credits",
        "--dry-run",
        "--compare",
        "--suite",
        "--case",
        "--extensive-size",
        "--parallel",
        "--judge-model",
        "--image",
        "--output",
        "--json",
      ]) {
        assert.ok(help.includes(fragment), `expected benchmark help to mention ${fragment}`);
        assert.ok(doc.includes(fragment), `expected benchmark docs to mention ${fragment}`);
      }
      assert.ok(doc.includes("1` to `5"));
      assert.ok(doc.includes("scores `4` and `5` pass"));
    });
  });

  it("authentication docs cover both pair login and terminal signup", () => {
    const doc = readRepoText("docs/user-guide/cli/authentication.md");
    const signupHelp = runCli(["signup", "--help"]);
    docAssert("cli-authentication-docs-cover-login-and-signup", () => {
      assert.ok(doc.includes("openmates login"));
      assert.ok(doc.includes("openmates signup"));
      assert.ok(doc.includes("hidden prompts"));
      assert.ok(signupHelp.includes("--backup-codes-output"));
      assert.ok(!doc.includes("pair-auth only"));
    });
  });

  it("settings docs cover executable notification commands", () => {
    const doc = readRepoText("docs/user-guide/cli/settings.md");
    const help = runCli(["settings", "notifications", "--help"]);
    docAssert("cli-settings-docs-cover-notification-commands", () => {
      for (const command of [
        "notifications status",
        "notifications list",
        "notifications stream",
        "notifications email set",
        "notifications backup set",
      ]) {
        assert.ok(help.includes(command), `expected settings help to mention ${command}`);
        assert.ok(doc.includes(`openmates settings ${command}`), `expected settings docs to mention ${command}`);
      }
    });
  });

  it("apps docs cover code run commands exposed by help", () => {
    const doc = readRepoText("docs/user-guide/cli/apps-and-skills.md");
    const help = runCli(["apps", "--help"]);
    docAssert("cli-apps-docs-cover-code-run-commands", () => {
      for (const fragment of [
        "apps code run --language",
        "apps code run --entry main.py --file",
        "apps code run --entry main.py --dir",
      ]) {
        assert.ok(help.includes(fragment), `expected app help to mention ${fragment}`);
        assert.ok(doc.includes(`openmates ${fragment}`), `expected apps docs to mention openmates ${fragment}`);
      }
    });
  });

  it("docs command reference matches docs help", () => {
    const doc = readRepoText("docs/user-guide/cli/docs.md");
    const help = runCli(["docs", "--help"]);
    docAssert("cli-docs-command-reference-matches-help", () => {
      for (const command of ["docs list", "docs search", "docs show", "docs download"]) {
        assert.ok(help.includes(command), `expected docs help to mention ${command}`);
        assert.ok(doc.includes(`openmates ${command}`), `expected docs reference to mention ${command}`);
      }
      assert.ok(doc.includes("docs download --all"));
      assert.ok(!doc.includes("docs get"));
    });
  });

  it("chat help lists documented chat operations", () => {
    const output = runCli(["chats", "--help"]);
    docAssert("cli-chats-help-lists-chat-operations", () => {
      for (const operation of ["list", "search", "show", "send", "share", "download", "delete", "incognito"]) {
        assert.ok(output.includes(operation), `expected chat help to mention ${operation}`);
      }
    });
  });

  it("chat docs cover logged-out example chat behavior", () => {
    const doc = readRepoText("docs/user-guide/cli/chats.md");
    const output = runCliWithoutSession(["chats", "list", "--limit", "1"]);
    docAssert("cli-unauthenticated-example-chats", () => {
      assert.ok(output.includes("EXAMPLE CHAT"));
      assert.ok(doc.includes("public example chats"));
      assert.ok(doc.includes("EXAMPLE CHAT"));
      assert.ok(doc.includes("openmates chats show example-gigantic-airplanes"));
    });
  });

  it("embeds and mentions help list sharing and mention operations", () => {
    const embeds = runCli(["embeds", "--help"]);
    const mentions = runCli(["mentions", "--help"]);
    docAssert("cli-embeds-sharing-help-lists-commands", () => {
      assert.ok(embeds.includes("share"));
      assert.ok(mentions.includes("search"));
    });
  });

  it("embeds docs cover Remotion video create terminal rendering", () => {
    const doc = readRepoText("docs/user-guide/cli/embeds-and-sharing.md");
    const renderer = readRepoText("frontend/packages/openmates-cli/src/embedRenderers.ts");
    docAssert("cli-embeds-docs-cover-remotion-video-create", () => {
      assert.ok(renderer.includes('case "videos/create"'));
      assert.ok(renderer.includes("Run again after rendering finishes"));
      assert.ok(doc.includes("videos/create"));
      assert.ok(doc.includes("Run the command again after rendering finishes"));
    });
  });
});
