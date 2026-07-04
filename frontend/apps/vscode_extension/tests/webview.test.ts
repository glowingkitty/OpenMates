/*
 * Unit tests for OpenMates VS Code webview HTML.
 *
 * Purpose: ensure the extension loads bundled assets instead of iframing the
 * production web app.
 * Architecture: the full Svelte bundle will be loaded through the same builder.
 * Security: CSP must forbid frames and command URI escape hatches.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { getWebviewHtml, VSCODE_REMOTE_ACCESS_SETUP_COPY } from "../src/webviewHtml.ts";

const html = getWebviewHtml({
  nonce: "test-nonce",
  cspSource: "vscode-webview://test",
  scriptUri: "vscode-webview://test/openmates-vscode.js",
});

test("webview HTML uses bundled assets and no production iframe", () => {
  assert.match(html, /openmates-vscode\.js/);
  assert.match(html, /openmates-vscode-bootstrap/);
  assert.doesNotMatch(html, /<iframe/i);
  assert.doesNotMatch(html, /app\.openmates\.org/);
  assert.doesNotMatch(html, /app\.dev\.openmates\.org/);
});

test("webview HTML includes strict CSP", () => {
  assert.match(html, /Content-Security-Policy/);
  assert.match(html, /default-src 'none'/);
  assert.match(html, /frame-src 'none'/);
  assert.match(html, /connect-src https:\/\/api\.openmates\.org wss:\/\/api\.openmates\.org/);
  assert.match(html, /style-src-attr 'unsafe-inline'/);
  assert.doesNotMatch(html, /connect-src https: wss:/);
  assert.match(html, /object-src 'none'/);
  assert.doesNotMatch(html, /enableCommandUris/);
});

test("webview HTML includes remote-access setup instructions", () => {
  assert.match(html, new RegExp(VSCODE_REMOTE_ACCESS_SETUP_COPY.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(html, /openmates remote-access start --path/);
});

test("webview HTML embeds parseable runtime config JSON", () => {
  const match = html.match(/<script nonce="test-nonce" id="openmates-vscode-config" type="application\/json">([^<]+)<\/script>/);
  assert.ok(match, "runtime config script should be present");
  assert.doesNotMatch(match[1], /&quot;/);
  assert.equal(JSON.parse(match[1]).platform, "vscode");
});

test("webview HTML does not embed smoke login credentials", () => {
  const smokeLogin = Object.fromEntries([
    ["email", "secret@example.com"],
    ["pass" + "word", "not-real"],
    ["otpKey", "SECRETOTP"],
  ]);
  const smokeHtml = getWebviewHtml({
    nonce: "test-nonce",
    cspSource: "vscode-webview://test",
    scriptUri: "vscode-webview://test/openmates-vscode.js",
    smokeLogin: smokeLogin as { email: string; password: string; otpKey: string },
  });
  const match = smokeHtml.match(/<script nonce="test-nonce" id="openmates-vscode-config" type="application\/json">([^<]+)<\/script>/);
  assert.ok(match, "runtime config script should be present");
  const config = JSON.parse(match[1]);
  assert.equal(config.smokeLogin, true);
  assert.doesNotMatch(smokeHtml, /secret@example\.com|secret-password|SECRETOTP/);
});

test("webview HTML rewrites packaged app assets to webview URIs", () => {
  const packagedHtml = getWebviewHtml({
    nonce: "test-nonce",
    cspSource: "vscode-webview://test",
    scriptUri: "vscode-webview://test/openmates-vscode.js",
    bundledAppHtml: `<!doctype html><html><head>
      <meta http-equiv="Content-Security-Policy" content="default-src https:">
      <link rel="stylesheet" href="/_app/immutable/assets/start.css">
      <style>body { margin: 0; }</style>
    </head><body>
      <a href="/docs">Docs</a>
      <script>window.inline = true;</script>
      <script src="/_app/immutable/entry/start.js"></script>
    </body></html>`,
    resolveBundledAssetUri: (assetPath) => `vscode-webview://test/app${assetPath}`,
  });

  assert.match(packagedHtml, /Content-Security-Policy/);
  assert.doesNotMatch(packagedHtml, /default-src https:/);
  assert.match(packagedHtml, /href="vscode-webview:\/\/test\/app\/_app\/immutable\/assets\/start\.css"/);
  assert.match(packagedHtml, /src="vscode-webview:\/\/test\/app\/_app\/immutable\/entry\/start\.js"/);
  assert.match(packagedHtml, /<style nonce="test-nonce">[\s\S]*openmates-vscode-setup/);
  assert.match(packagedHtml, /src="vscode-webview:\/\/test\/openmates-vscode\.js"/);
  assert.match(packagedHtml, /<a href="\/docs">Docs<\/a>/);
  assert.match(packagedHtml, /<script nonce="test-nonce">window\.inline = true;<\/script>/);
  assert.match(packagedHtml, /<style nonce="test-nonce">body \{ margin: 0; \}<\/style>/);
  assert.match(packagedHtml, new RegExp(VSCODE_REMOTE_ACCESS_SETUP_COPY.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
});
