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
import { execFile, execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { promisify } from "node:util";
import { WebSocketServer } from "ws";

// Import from compiled dist — the .js extension imports in src/ require the build step
import {
  deriveAppUrl,
  MEMORY_TYPE_REGISTRY,
  parseNewChatSuggestionText,
  serializeToYaml,
  getExtForLang,
  defaultCloneBranchForVersion,
} from "../dist/index.js";

const execFileAsync = promisify(execFile);

function runCli(args: string[], env: Record<string, string> = {}): string {
  return execFileSync("node", ["dist/cli.js", ...args], {
    cwd: fileURLToPath(new URL("..", import.meta.url)),
    encoding: "utf-8",
    env: { ...process.env, TERM: "dumb", ...env },
    timeout: 15_000,
  });
}

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
    cwd: fileURLToPath(new URL("..", import.meta.url)),
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

  it("falls back to production for unknown API URLs", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("https://api.custom-instance.example.com"),
      "https://openmates.org",
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
    assert.strictEqual(defaultCloneBranchForVersion("0.11.0-alpha.12"), "dev");
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
// parseNewChatSuggestionText
// ---------------------------------------------------------------------------

describe("parseNewChatSuggestionText", () => {
  it("parses [app-skill] prefix with body", () => {
    const result = parseNewChatSuggestionText(
      "[web-search] What's the latest AI news?",
    );
    assert.strictEqual(result.appId, "web");
    assert.strictEqual(result.skillId, "search");
    assert.strictEqual(result.body, "What's the latest AI news?");
  });

  it("parses [images-generate] prefix", () => {
    const result = parseNewChatSuggestionText(
      "[images-generate] Draw a futuristic city at sunset",
    );
    assert.strictEqual(result.appId, "images");
    assert.strictEqual(result.skillId, "generate");
    assert.strictEqual(result.body, "Draw a futuristic city at sunset");
  });

  it("parses [news-search] prefix", () => {
    const result = parseNewChatSuggestionText("[news-search] Climate tech");
    assert.strictEqual(result.appId, "news");
    assert.strictEqual(result.skillId, "search");
    assert.strictEqual(result.body, "Climate tech");
  });

  it("parses [app] prefix without skill", () => {
    const result = parseNewChatSuggestionText("[web] Open my bookmarks");
    assert.strictEqual(result.appId, "web");
    assert.strictEqual(result.skillId, null);
    assert.strictEqual(result.body, "Open my bookmarks");
  });

  it("returns body unchanged when no prefix present", () => {
    const result = parseNewChatSuggestionText(
      "How do I implement a binary search tree?",
    );
    assert.strictEqual(result.appId, null);
    assert.strictEqual(result.skillId, null);
    assert.strictEqual(result.body, "How do I implement a binary search tree?");
  });

  it("trims whitespace from body", () => {
    const result = parseNewChatSuggestionText(
      "[math-calculate]   Solve 42 * 13 + 7  ",
    );
    assert.strictEqual(result.appId, "math");
    assert.strictEqual(result.skillId, "calculate");
    assert.strictEqual(result.body, "Solve 42 * 13 + 7");
  });

  it("handles suggestion with only the prefix and no body", () => {
    const result = parseNewChatSuggestionText("[videos-search]");
    assert.strictEqual(result.appId, "videos");
    assert.strictEqual(result.skillId, "search");
    assert.strictEqual(result.body, "");
  });

  it("treats plain text starting with a non-bracket char as plain body", () => {
    const result = parseNewChatSuggestionText(
      "Tell me about quantum computing",
    );
    assert.strictEqual(result.appId, null);
    assert.strictEqual(result.skillId, null);
    assert.strictEqual(result.body, "Tell me about quantum computing");
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
  suggestion: { body: string; appId: string | null; skillId: string | null },
  index: number,
): string {
  const appLabel = suggestion.skillId
    ? `[${suggestion.appId}-${suggestion.skillId}] `
    : suggestion.appId
      ? `[${suggestion.appId}] `
      : "";
  const escaped = suggestion.body.replace(/"/g, '\\"');
  return (
    `${index}. ${appLabel}${suggestion.body}\n` +
    `   openmates chats new "${escaped}"\n`
  );
}

describe("new chat suggestions rendering", () => {
  it("renders a skill-prefixed suggestion with app/skill label", () => {
    const s = parseNewChatSuggestionText(
      "[web-search] Latest quantum computing breakthroughs",
    );
    const output = renderNewChatSuggestion(s, 1);
    assert.ok(output.startsWith("1. [web-search]"));
    assert.ok(output.includes("Latest quantum computing breakthroughs"));
    assert.ok(
      output.includes(
        'openmates chats new "Latest quantum computing breakthroughs"',
      ),
    );
  });

  it("renders a plain suggestion without prefix", () => {
    const s = parseNewChatSuggestionText(
      "Explain the history of the Roman Empire",
    );
    const output = renderNewChatSuggestion(s, 3);
    assert.ok(output.startsWith("3. Explain the history"));
    assert.ok(output.includes('openmates chats new "Explain the history'));
  });

  it("renders an app-only prefixed suggestion (no skill)", () => {
    const s = parseNewChatSuggestionText("[images] Generate a logo for my app");
    const output = renderNewChatSuggestion(s, 2);
    assert.ok(output.startsWith("2. [images]"));
    assert.ok(output.includes("Generate a logo for my app"));
  });

  it("correctly numbers multiple suggestions", () => {
    const suggestions = [
      "[web-search] AI trends in 2026",
      "[news-search] Startup funding news",
      "How to improve my sleep?",
    ];
    const outputs = suggestions.map((text, i) => {
      const s = parseNewChatSuggestionText(text);
      return renderNewChatSuggestion(s, i + 1);
    });
    assert.ok(outputs[0].startsWith("1."));
    assert.ok(outputs[1].startsWith("2."));
    assert.ok(outputs[2].startsWith("3."));
  });

  it("escapes double quotes in suggestion body for shell safety", () => {
    const s = parseNewChatSuggestionText(
      'Summarize the book "Thinking Fast and Slow"',
    );
    const output = renderNewChatSuggestion(s, 1);
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

describe("documented CLI command reference", () => {
  it("top-level help lists the user guide command categories", () => {
    const output = runCli(["--help"]);
    docAssert("cli-readme-lists-command-categories", () => {
      for (const command of ["login", "chats", "apps", "settings", "embeds", "mentions", "server"]) {
        assert.ok(output.includes(command), `expected top-level help to mention ${command}`);
      }
    });
    docAssert("cli-authentication-uses-pair-login-command", () => {
      assert.ok(output.includes("login"));
      assert.ok(!output.includes("password"));
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

  it("embeds and mentions help list sharing and mention operations", () => {
    const embeds = runCli(["embeds", "--help"]);
    const mentions = runCli(["mentions", "--help"]);
    docAssert("cli-embeds-sharing-help-lists-commands", () => {
      assert.ok(embeds.includes("share"));
      assert.ok(mentions.includes("search"));
    });
  });
});
