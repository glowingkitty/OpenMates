// tests/codeRunInput.test.ts
/**
 * Unit tests for CLI Code Run input materialization.
 *
 * Run: node --test --experimental-strip-types tests/codeRunInput.test.ts
 */

import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

import {
  buildCodeRunRequestsFromFlags,
  buildCodeRunStreamUrl,
} from "../src/codeRunInput.ts";

const testDir = join(tmpdir(), `openmates-code-run-${Date.now()}`);

function b64(value: string): string {
  return Buffer.from(value, "utf8").toString("base64");
}

describe("codeRunInput", () => {
  beforeEach(() => {
    mkdirSync(testDir, { recursive: true });
  });

  afterEach(() => {
    rmSync(testDir, { recursive: true, force: true });
    delete (globalThis as typeof globalThis & { fetch?: unknown }).fetch;
  });

  it("builds inline code requests with internet enabled by default", async () => {
    const requests = await buildCodeRunRequestsFromFlags({
      language: "python",
      filename: "hello.py",
      code: "print('hello')\n",
    });

    assert.deepEqual(requests, [{
      mode: "direct",
      entry_path: "hello.py",
      enable_internet: true,
      files: [{
        path: "hello.py",
        content_base64: b64("print('hello')\n"),
        language: "python",
        mime_type: "text/plain",
        is_target: true,
      }],
    }]);
  });

  it("packages local files and disables internet with noInternet", async () => {
    const filePath = join(testDir, "app.py");
    writeFileSync(filePath, "print('file')\n");

    const requests = await buildCodeRunRequestsFromFlags({
      entry: "app.py",
      file: [filePath],
      noInternet: true,
    });

    assert.equal(requests[0].enable_internet, false);
    assert.equal(requests[0].entry_path, "app.py");
    assert.equal(requests[0].files[0].path, "app.py");
    assert.equal(requests[0].files[0].content_base64, b64("print('file')\n"));
  });

  it("packages directories with default ignores and explicit excludes", async () => {
    mkdirSync(join(testDir, "project", "__pycache__"), { recursive: true });
    mkdirSync(join(testDir, "project", "src"), { recursive: true });
    writeFileSync(join(testDir, "project", "main.py"), "print('main')\n");
    writeFileSync(join(testDir, "project", "src", "helper.py"), "HELPER = True\n");
    writeFileSync(join(testDir, "project", "__pycache__", "main.pyc"), "ignored");
    writeFileSync(join(testDir, "project", "debug.log"), "ignored");

    const requests = await buildCodeRunRequestsFromFlags({
      entry: "main.py",
      dir: join(testDir, "project"),
      exclude: ["*.log"],
    });

    const paths = requests[0].files.map((file) => file.path).sort();
    assert.deepEqual(paths, ["main.py", "src/helper.py"]);
    assert.equal(requests[0].files.find((file) => file.path === "main.py")?.is_target, true);
  });

  it("downloads raw URL files client-side", async () => {
    (globalThis as typeof globalThis & { fetch: typeof fetch }).fetch = async () => new Response("print('url')\n", { status: 200 });

    const requests = await buildCodeRunRequestsFromFlags({
      entry: "main.py",
      url: ["https://raw.githubusercontent.com/org/repo/main/main.py"],
    });

    assert.deepEqual(requests[0].files, [{
      path: "main.py",
      content_base64: b64("print('url')\n"),
      language: "python",
      mime_type: "text/plain",
      is_target: true,
    }]);
  });

  it("downloads public GitHub repo include paths client-side", async () => {
    const fetchedUrls: string[] = [];
    (globalThis as typeof globalThis & { fetch: typeof fetch }).fetch = async (url) => {
      fetchedUrls.push(String(url));
      return new Response("print('repo')\n", { status: 200 });
    };

    const requests = await buildCodeRunRequestsFromFlags({
      entry: "examples/main.py",
      repo: "https://github.com/openmates/example-repo",
      include: ["examples/main.py"],
    });

    assert.deepEqual(fetchedUrls, ["https://raw.githubusercontent.com/openmates/example-repo/main/examples/main.py"]);
    assert.equal(requests[0].files[0].path, "examples/main.py");
    assert.equal(requests[0].files[0].content_base64, b64("print('repo')\n"));
    assert.equal(requests[0].files[0].is_target, true);
  });

  it("rejects unsafe local paths before upload", async () => {
    await assert.rejects(
      () => buildCodeRunRequestsFromFlags({ entry: "../main.py", file: [join(testDir, "main.py")] }),
      /Unsafe Code Run path/,
    );
  });

  it("builds authenticated Code Run stream URLs for CLI sessions", () => {
    const url = buildCodeRunStreamUrl({
      apiUrl: "https://api.dev.openmates.org",
      executionId: "exec-1",
      sessionId: "cli-session",
      token: "ws-token",
    });

    assert.equal(url, "wss://api.dev.openmates.org/v1/code/run/exec-1/stream?sessionId=cli-session&token=ws-token");
  });
});
