/*
 * OpenMates VS Code webview HTML builder.
 *
 * Purpose: load bundled OpenMates app assets inside VS Code without iframing the
 * production web app.
 * Architecture: extension.ts passes webview-safe asset URIs and a nonce.
 * Security: CSP forbids frames by default and only allows bundled scripts with
 * the generated nonce.
 */

export interface WebviewHtmlOptions {
  nonce: string;
  cspSource: string;
  scriptUri: string;
  bundledAppHtml?: string;
  resolveBundledAssetUri?: (assetPath: string) => string;
  apiBaseUrl?: string;
  smokeLogin?: WebviewSmokeLoginConfig;
}

export interface WebviewSmokeLoginConfig {
  email: string;
  password: string;
  otpKey?: string;
}

export const VSCODE_REMOTE_ACCESS_SETUP_COPY =
  "Install and start the OpenMates CLI on each machine where you want OpenMates to access project files.";

export function getWebviewHtml(options: WebviewHtmlOptions): string {
  if (options.bundledAppHtml && options.resolveBundledAssetUri) {
    return getBundledAppHtml(options);
  }

  const apiBaseUrl = options.apiBaseUrl ?? "https://api.openmates.org";
  const csp = buildContentSecurityPolicy(options, apiBaseUrl);
  const config = escapeJsonScript(JSON.stringify({
    platform: "vscode",
    loginMode: "pair_only",
    apiBaseUrl,
    remoteAccessSetupCopy: VSCODE_REMOTE_ACCESS_SETUP_COPY,
    smokeLogin: Boolean(options.smokeLogin),
  }));
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta http-equiv="Content-Security-Policy" content="${escapeHtml(csp)}" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>OpenMates</title>
    <style nonce="${options.nonce}">${BOOTSTRAP_CSS}</style>
  </head>
  <body data-openmates-platform="vscode">
    <script nonce="${options.nonce}" id="openmates-vscode-config" type="application/json">${config}</script>
    <div id="openmates-root" data-testid="openmates-vscode-root">
      <section class="openmates-vscode-bootstrap" data-testid="vscode-remote-access-setup">
        <h1>OpenMates</h1>
        <p>${escapeHtml(VSCODE_REMOTE_ACCESS_SETUP_COPY)}</p>
        <pre><code>npm install -g openmates
openmates login
openmates remote-access start --path ./my-project</code></pre>
      </section>
    </div>
    <script nonce="${options.nonce}" src="${options.scriptUri}"></script>
  </body>
</html>`;
}

function getBundledAppHtml(options: WebviewHtmlOptions): string {
  const rawHtml = options.bundledAppHtml ?? "";
  const apiBaseUrl = options.apiBaseUrl ?? "https://api.openmates.org";
  const csp = buildContentSecurityPolicy(options, apiBaseUrl);
  const config = escapeJsonScript(JSON.stringify({
    platform: "vscode",
    loginMode: "pair_only",
    apiBaseUrl,
    remoteAccessSetupCopy: VSCODE_REMOTE_ACCESS_SETUP_COPY,
    smokeLogin: Boolean(options.smokeLogin),
  }));
  const setupHtml = `<section class="openmates-vscode-setup" data-testid="vscode-remote-access-setup"><strong>VS Code setup:</strong> ${escapeHtml(VSCODE_REMOTE_ACCESS_SETUP_COPY)} <code>openmates remote-access start --path ./my-project</code></section>`;
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${escapeHtml(csp)}" />`;
  const configScript = `<script nonce="${options.nonce}" id="openmates-vscode-config" type="application/json">${config}</script>`;
  const bootstrapStyle = `<style nonce="${options.nonce}">${BOOTSTRAP_CSS}</style>`;
  const bootstrapScript = `<script nonce="${options.nonce}" src="${options.scriptUri}"></script>`;

  let html = rawHtml
    .replace(/<meta[^>]+http-equiv=["']Content-Security-Policy["'][^>]*>/gi, "")
    .replace(/<(script|style)\b([^>]*)>/gi, (match, tagName: string, attrs: string) => {
      if (/\snonce=/i.test(attrs)) return match;
      return `<${tagName} nonce="${options.nonce}"${attrs}>`;
    })
    .replace(/<(script|img|source|video|audio)\b([^>]*?)\ssrc=["']\/(?!\/)([^"'#?]+)([^"']*)["']([^>]*)>/gi, rewriteBundledSrc(options))
    .replace(/<(script|img|source|video|audio)\b([^>]*?)\ssrc=["']\.\/([^"'#?]+)([^"']*)["']([^>]*)>/gi, rewriteBundledSrc(options))
    .replace(/<link\b([^>]*?)\shref=["']\/(?!\/)([^"'#?]+)([^"']*)["']([^>]*)>/gi, rewriteBundledLink(options))
    .replace(/<link\b([^>]*?)\shref=["']\.\/([^"'#?]+)([^"']*)["']([^>]*)>/gi, rewriteBundledLink(options));

  html = html.replace(/<head(\s[^>]*)?>/i, (match) => `${match}\n    ${cspMeta}\n    ${configScript}\n    ${bootstrapStyle}`);
  html = html.replace(/<body(\s[^>]*)?>/i, (match) => `${match}\n    ${setupHtml}`);
  html = html.replace(/<\/body>/i, `    ${bootstrapScript}\n  </body>`);
  return html;
}

function rewriteBundledSrc(options: WebviewHtmlOptions) {
  return (_match: string, tagName: string, before: string, pathname: string, suffix: string, after: string) => {
    const assetPath = `/${pathname}${suffix}`;
    return `<${tagName}${before} src="${options.resolveBundledAssetUri?.(assetPath)}"${after}>`;
  };
}

function rewriteBundledLink(options: WebviewHtmlOptions) {
  return (_match: string, before: string, pathname: string, suffix: string, after: string) => {
    const assetPath = `/${pathname}${suffix}`;
    return `<link${before} href="${options.resolveBundledAssetUri?.(assetPath)}"${after}>`;
  };
}

function buildContentSecurityPolicy(options: WebviewHtmlOptions, apiBaseUrl: string): string {
  const connectSources = buildConnectSources(apiBaseUrl).join(" ");
  return [
    "default-src 'none'",
    `script-src 'nonce-${options.nonce}' ${options.cspSource}`,
    `style-src 'nonce-${options.nonce}' ${options.cspSource}`,
    "style-src-attr 'unsafe-inline'",
    `img-src ${options.cspSource} https: data:`,
    `connect-src ${connectSources}`,
    `font-src ${options.cspSource} https: data:`,
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'none'",
  ].join("; ");
}

const BOOTSTRAP_CSS = `
:root {
  color-scheme: light dark;
  font-family: "Lexend Deca", system-ui, sans-serif;
}

body {
  margin: 0;
  min-height: 100vh;
  background: #f6f6f6;
  color: #1f2933;
}

.openmates-vscode-bootstrap {
  box-sizing: border-box;
  max-width: 760px;
  margin: 8vh auto;
  padding: 32px;
  border-radius: 28px;
  background: #ffffff;
  box-shadow: 0 14px 45px rgb(15 23 42 / 14%);
}

.openmates-vscode-bootstrap h1 {
  margin: 0 0 16px;
  font-size: 32px;
}

.openmates-vscode-bootstrap p {
  margin: 0 0 20px;
  line-height: 1.6;
}

.openmates-vscode-bootstrap pre {
  overflow: auto;
  padding: 18px;
  border-radius: 16px;
  background: #111827;
  color: #f9fafb;
}

.openmates-vscode-setup {
  box-sizing: border-box;
  padding: 10px 16px;
  border-bottom: 1px solid rgb(15 23 42 / 12%);
  background: #ffffff;
  color: #1f2933;
  font-size: 13px;
  line-height: 1.45;
}

.openmates-vscode-setup code {
  padding: 2px 5px;
  border-radius: 6px;
  background: #eef2f7;
}`;

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeJsonScript(value: string): string {
  return value
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function buildConnectSources(apiBaseUrl: string): string[] {
  const apiUrl = new URL(apiBaseUrl);
  const wsUrl = new URL(apiUrl.toString());
  wsUrl.protocol = apiUrl.protocol === "http:" ? "ws:" : "wss:";
  return [
    apiUrl.origin,
    wsUrl.origin,
    "https://api.openmates.org",
    "wss://api.openmates.org",
    "https://api.dev.openmates.org",
    "wss://api.dev.openmates.org",
  ];
}
