/*
 * Unit tests for OpenMates VS Code bridge allowlist.
 *
 * Purpose: verify V1 exposes only readonly/native convenience messages.
 * Architecture: handler tests run without a VS Code Extension Host.
 * Security: mutation-like messages must fail before reaching VS Code APIs.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  ALLOWED_WEBVIEW_MESSAGE_TYPES,
  assertNoMutationMessageTypes,
  FORBIDDEN_V1_MESSAGE_TYPES,
  handleWebviewMessage,
  isAllowedWebviewMessageType,
} from "../src/bridge.ts";

test("bridge allowlist contains no V1 mutation messages", () => {
  assertNoMutationMessageTypes();
  for (const forbidden of FORBIDDEN_V1_MESSAGE_TYPES) {
    assert.equal(ALLOWED_WEBVIEW_MESSAGE_TYPES.includes(forbidden as never), false, forbidden);
    assert.equal(isAllowedWebviewMessageType(forbidden), false, forbidden);
  }
});

test("bridge dispatches allowed messages", async () => {
  const calls: string[] = [];
  await handleWebviewMessage({ type: "reportReady" }, {
    openFile: () => calls.push("openFile"),
    showDiff: () => calls.push("showDiff"),
    copyText: () => calls.push("copyText"),
    reportReady: () => calls.push("reportReady"),
  });
  assert.deepEqual(calls, ["reportReady"]);
});

test("bridge rejects unsupported mutation messages", async () => {
  await assert.rejects(
    () => handleWebviewMessage({ type: "runCommand", command: "npm test" }, {
      openFile: () => undefined,
      showDiff: () => undefined,
      copyText: () => undefined,
      reportReady: () => undefined,
    }),
    /Unsupported OpenMates VS Code bridge message/,
  );
});

test("bridge rejects unsafe paths and oversized fields", async () => {
  await assert.rejects(
    () => handleWebviewMessage({ type: "openFile", path: "../secret.txt" }, {
      openFile: () => undefined,
      showDiff: () => undefined,
      copyText: () => undefined,
      reportReady: () => undefined,
    }),
    /Invalid OpenMates VS Code bridge path/,
  );

  await assert.rejects(
    () => handleWebviewMessage({ type: "copyText", text: "x".repeat(2_000_001) }, {
      openFile: () => undefined,
      showDiff: () => undefined,
      copyText: () => undefined,
      reportReady: () => undefined,
    }),
    /Invalid OpenMates VS Code bridge field: text/,
  );
});

test("bridge rejects malformed messages", async () => {
  await assert.rejects(
    () => handleWebviewMessage({ nope: true }, {
      openFile: () => undefined,
      showDiff: () => undefined,
      copyText: () => undefined,
      reportReady: () => undefined,
    }),
    /Invalid OpenMates VS Code bridge message/,
  );
});
