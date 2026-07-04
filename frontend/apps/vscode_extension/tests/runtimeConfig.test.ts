/*
 * Unit tests for the shared OpenMates runtime adapter.
 *
 * Purpose: verify VS Code webview config is parsed by shared UI code.
 * Architecture: the extension injects #openmates-vscode-config before the app bundle.
 * Security: pair-only mode must be opt-in and malformed config must fall back to browser mode.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { getOpenMatesRuntimeConfig, isVscodePairOnlyLogin } from "../../../packages/ui/src/platform/runtime.ts";

const originalDocument = globalThis.document;
const originalWarn = console.warn;

test.afterEach(() => {
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: originalDocument,
  });
  console.warn = originalWarn;
});

test("runtime config defaults to browser mode without injected config", () => {
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: undefined,
  });

  assert.deepEqual(getOpenMatesRuntimeConfig(), {
    platform: "browser",
    loginMode: "default",
  });
  assert.equal(isVscodePairOnlyLogin(), false);
});

test("runtime config enables VS Code pair-only mode from injected JSON", () => {
  setConfigElement(JSON.stringify({
    platform: "vscode",
    loginMode: "pair_only",
    apiBaseUrl: "https://api.dev.openmates.org",
    remoteAccessSetupCopy: "Install the CLI.",
  }));

  assert.deepEqual(getOpenMatesRuntimeConfig(), {
    platform: "vscode",
    loginMode: "pair_only",
    apiBaseUrl: "https://api.dev.openmates.org",
    remoteAccessSetupCopy: "Install the CLI.",
  });
  assert.equal(isVscodePairOnlyLogin(), true);
});

test("runtime config ignores malformed injected JSON", () => {
  setConfigElement("{");
  console.warn = () => undefined;

  assert.equal(getOpenMatesRuntimeConfig().platform, "browser");
  assert.equal(isVscodePairOnlyLogin(), false);
});

function setConfigElement(textContent: string): void {
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      getElementById: (id: string) => id === "openmates-vscode-config" ? { textContent } : null,
    },
  });
}
