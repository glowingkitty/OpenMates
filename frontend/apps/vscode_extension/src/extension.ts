/*
 * OpenMates VS Code extension entry point.
 *
 * Purpose: host the bundled OpenMates app shell inside a VS Code webview.
 * Architecture: workspace-preferred extension with a tiny native bridge for
 * open-file and readonly diff actions.
 * Security: V1 does not expose local write, patch apply, command execution,
 * package install, test execution, or git mutation authority.
 */

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import * as vscode from "vscode";

import { getSafeBundledAssetSegments } from "./assetPaths.js";
import { handleWebviewMessage } from "./bridge.js";
import { getReconnectPolicy } from "./state.js";
import { getWebviewHtml, type WebviewSmokeLoginConfig } from "./webviewHtml.js";

const VIEW_TYPE = "openmates.app";
const SMOKE_LOGIN_TIMEOUT_MS = 45_000;
const SMOKE_FETCH_TIMEOUT_MS = 15_000;

let outputChannel: vscode.OutputChannel | undefined;

export function activate(context: vscode.ExtensionContext): void {
  outputChannel = vscode.window.createOutputChannel("OpenMates");
  outputChannel.appendLine(`OpenMates VS Code extension activated in mode ${context.extensionMode}.`);
  outputChannel.appendLine(`Reconnect policy: ${JSON.stringify(getReconnectPolicy())}`);

  const subscriptions: vscode.Disposable[] = [
    outputChannel,
    vscode.commands.registerCommand("openmates.open", () => openOpenMates(context)),
    vscode.commands.registerCommand("openmates.checkRemoteAccessSetup", () => showRemoteAccessSetup()),
    vscode.commands.registerCommand("openmates.showLogs", () => outputChannel?.show()),
  ];
  if (process.env.OPENMATES_VSCODE_ENABLE_SMOKE_LOGIN === "1") {
    subscriptions.push(vscode.commands.registerCommand("openmates.internal.loginSmoke", () => runLoginSmoke(context)));
  }
  context.subscriptions.push(...subscriptions);
}

export function deactivate(): void {
  outputChannel?.appendLine("OpenMates VS Code extension deactivated.");
}

interface OpenOpenMatesOptions {
  smokeLogin?: WebviewSmokeLoginConfig;
  onSmokeLoginResult?: (message: Record<string, unknown>) => void;
  forceBootstrap?: boolean;
}

async function openOpenMates(context: vscode.ExtensionContext, options: OpenOpenMatesOptions = {}): Promise<void> {
  const panel = vscode.window.createWebviewPanel(
    VIEW_TYPE,
    "OpenMates",
    vscode.ViewColumn.Beside,
    {
      enableScripts: true,
      enableCommandUris: false,
      localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "media")],
      retainContextWhenHidden: true,
    },
  );
  const nonce = crypto.randomBytes(16).toString("base64");
  const bundledAppHtml = options.forceBootstrap ? undefined : await readBundledAppHtml(context.extensionUri);
  const scriptUri = panel.webview.asWebviewUri(vscode.Uri.joinPath(context.extensionUri, "media", "openmates-vscode.js"));
  panel.webview.html = getWebviewHtml({
    nonce,
    cspSource: panel.webview.cspSource,
    scriptUri: scriptUri.toString(),
    bundledAppHtml,
    resolveBundledAssetUri: (assetPath) => resolveBundledAssetUri(panel.webview, context.extensionUri, assetPath),
    apiBaseUrl: process.env.OPENMATES_VSCODE_API_BASE_URL,
    smokeLogin: options.smokeLogin,
  });
  panel.webview.onDidReceiveMessage(
    async (message) => {
      try {
        if (isSmokeLoginResult(message)) {
          options.onSmokeLoginResult?.(message);
          return;
        }
        if (isSmokeLoginNativeRequest(message) && options.smokeLogin) {
          await handleSmokeLoginNativeRequest(panel.webview, message.requestId, options.smokeLogin);
          return;
        }
        await handleWebviewMessage(message, {
          openFile: async (openMessage) => {
            const uri = resolveWorkspaceFile(openMessage.path, openMessage.sourceId);
            if (!uri) throw new Error("No active VS Code workspace maps to this OpenMates source path.");
            await vscode.window.showTextDocument(uri, { preview: false });
          },
          showDiff: async (diffMessage) => {
            const leftUri = resolveWorkspaceFile(diffMessage.path, diffMessage.sourceId);
            if (!leftUri) throw new Error("No active VS Code workspace maps to this OpenMates diff path.");
            const rightDoc = await vscode.workspace.openTextDocument({
              content: diffMessage.modified,
              language: diffMessage.language ?? inferLanguage(diffMessage.path),
            });
            await vscode.commands.executeCommand("vscode.diff", leftUri, rightDoc.uri, `OpenMates diff: ${diffMessage.path}`);
          },
          copyText: async (copyMessage) => vscode.env.clipboard.writeText(copyMessage.text),
          reportReady: () => outputChannel?.appendLine("OpenMates webview reported ready."),
        });
      } catch (error) {
        const messageText = error instanceof Error ? error.message : String(error);
        outputChannel?.appendLine(`Bridge error: ${messageText}`);
        await panel.webview.postMessage({ type: "nativeActionResult", ok: false, error: messageText });
      }
    },
    undefined,
    context.subscriptions,
  );
}

async function runLoginSmoke(context: vscode.ExtensionContext): Promise<Record<string, unknown>> {
  const smokeLogin = getSmokeLoginConfig();
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("VS Code webview login smoke timed out.")), SMOKE_LOGIN_TIMEOUT_MS);
    openOpenMates(context, {
      smokeLogin,
      forceBootstrap: process.env.OPENMATES_VSCODE_SMOKE_USE_BOOTSTRAP === "1",
      onSmokeLoginResult: (message) => {
        clearTimeout(timeout);
        if (message.ok === true) {
          outputChannel?.appendLine("OpenMates VS Code webview login smoke succeeded.");
          resolve(message);
        } else {
          reject(new Error(typeof message.error === "string" ? message.error : "VS Code webview login smoke failed."));
        }
      },
    }).catch((error) => {
      clearTimeout(timeout);
      reject(error);
    });
  });
}

function getSmokeLoginConfig(): WebviewSmokeLoginConfig {
  const workerSlot = process.env.PLAYWRIGHT_WORKER_SLOT || "1";
  const email = process.env[`OPENMATES_TEST_ACCOUNT_${workerSlot}_EMAIL`] || process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
  const password = process.env[`OPENMATES_TEST_ACCOUNT_${workerSlot}_PASSWORD`] || process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
  if (!email || !password) {
    throw new Error("OPENMATES_TEST_ACCOUNT_EMAIL/OPENMATES_TEST_ACCOUNT_<slot>_EMAIL and OPENMATES_TEST_ACCOUNT_PASSWORD/OPENMATES_TEST_ACCOUNT_<slot>_PASSWORD are required for VS Code login smoke.");
  }
  return {
    email,
    password,
    otpKey: process.env[`OPENMATES_TEST_ACCOUNT_${workerSlot}_OTP_KEY`] || process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY,
  };
}

function isSmokeLoginResult(message: unknown): message is Record<string, unknown> {
  return process.env.OPENMATES_VSCODE_ENABLE_SMOKE_LOGIN === "1" &&
    typeof message === "object" &&
    message !== null &&
    "type" in message &&
    (message as { type?: unknown }).type === "loginSmokeResult";
}

function isSmokeLoginNativeRequest(message: unknown): message is { requestId: string } {
  return process.env.OPENMATES_VSCODE_ENABLE_SMOKE_LOGIN === "1" &&
    typeof message === "object" &&
    message !== null &&
    "type" in message &&
    (message as { type?: unknown }).type === "loginSmokeNativeRequest" &&
    typeof (message as { requestId?: unknown }).requestId === "string";
}

async function handleSmokeLoginNativeRequest(
  webview: vscode.Webview,
  requestId: string,
  smokeLogin: WebviewSmokeLoginConfig,
): Promise<void> {
  try {
    const result = await runNativeLoginSmoke(smokeLogin);
    await webview.postMessage({ type: "loginSmokeNativeResult", requestId, ok: true, ...result });
  } catch (error) {
    await webview.postMessage({
      type: "loginSmokeNativeResult",
      requestId,
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

async function runNativeLoginSmoke(smokeLogin: WebviewSmokeLoginConfig): Promise<Record<string, unknown>> {
  const apiBaseUrl = (process.env.OPENMATES_VSCODE_API_BASE_URL || "https://api.dev.openmates.org").replace(/\/$/, "");
  const normalizedEmail = smokeLogin.email.trim().toLowerCase();
  const hashedEmail = hashTextBase64(normalizedEmail);
  const lookupData = await postJson<{ user_email_salt?: string }>(apiBaseUrl, "/v1/auth/lookup", {
    hashed_email: hashedEmail,
    stay_logged_in: true,
  });
  if (!lookupData.user_email_salt) {
    throw new Error("lookup_missing_user_email_salt");
  }

  const salt = Buffer.from(lookupData.user_email_salt, "base64");
  const loginBody = {
    hashed_email: hashedEmail,
    lookup_hash: hashKeyBase64(smokeLogin.password, salt),
    stay_logged_in: true,
    session_id: crypto.randomUUID(),
    email_encryption_key: hashKeyBase64(normalizedEmail, salt),
  };

  let loginData = await postJson<Record<string, unknown>>(apiBaseUrl, "/v1/auth/login", loginBody);
  if (loginData.tfa_required === true) {
    if (!smokeLogin.otpKey) throw new Error("otp_required_but_missing");
    loginData = await postJson<Record<string, unknown>>(apiBaseUrl, "/v1/auth/login", {
      ...loginBody,
      tfa_code: generateTotp(smokeLogin.otpKey),
      code_type: "otp",
    });
  }

  if (loginData.success !== true) {
    throw new Error(`login_failed:${typeof loginData.message === "string" ? loginData.message : "unknown"}`);
  }
  const user = typeof loginData.user === "object" && loginData.user !== null ? loginData.user as Record<string, unknown> : null;
  return { userId: typeof user?.id === "string" ? user.id : null };
}

async function postJson<T>(apiBaseUrl: string, pathName: string, body: Record<string, unknown>): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), SMOKE_FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(`${apiBaseUrl}${pathName}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        Origin: deriveAppOrigin(apiBaseUrl),
        "User-Agent": "OpenMates VS Code/0.1",
        "X-OpenMates-SDK": "vscode-extension",
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = typeof data.message === "string" ? data.message : response.statusText;
      throw new Error(`api_request_failed:${pathName}:${response.status}:${message}`);
    }
    return data as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`api_request_timeout:${pathName}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function deriveAppOrigin(apiBaseUrl: string): string {
  const configured = process.env.OPENMATES_VSCODE_APP_ORIGIN?.replace(/\/$/, "");
  if (configured) return configured;
  const url = new URL(apiBaseUrl);
  if (url.hostname === "api.dev.openmates.org") return "https://app.dev.openmates.org";
  if (url.hostname === "api.openmates.org") return "https://openmates.org";
  if (url.hostname === "localhost" || url.hostname === "127.0.0.1") return "http://localhost:5173";
  if (url.hostname.startsWith("api.")) url.hostname = `app.${url.hostname.slice(4)}`;
  url.pathname = "";
  url.search = "";
  url.hash = "";
  return url.toString().replace(/\/$/, "");
}

function hashTextBase64(value: string): string {
  return crypto.createHash("sha256").update(value).digest("base64");
}

function hashKeyBase64(value: string, salt: Buffer): string {
  return crypto.createHash("sha256").update(Buffer.concat([Buffer.from(value), salt])).digest("base64");
}

function generateTotp(base32Secret: string): string {
  const counter = Buffer.alloc(8);
  counter.writeUInt32BE(Math.floor(Date.now() / 30000), 4);
  const signature = crypto.createHmac("sha1", base32ToBuffer(base32Secret)).update(counter).digest();
  const offset = signature[signature.length - 1] & 0xf;
  const code = ((signature[offset] & 0x7f) << 24) |
    ((signature[offset + 1] & 0xff) << 16) |
    ((signature[offset + 2] & 0xff) << 8) |
    (signature[offset + 3] & 0xff);
  return String(code % 1000000).padStart(6, "0");
}

function base32ToBuffer(secret: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const clean = secret.replace(/=+$/g, "").replace(/\s+/g, "").toUpperCase();
  let bits = "";
  for (const char of clean) {
    const value = alphabet.indexOf(char);
    if (value === -1) throw new Error("invalid_otp_secret");
    bits += value.toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let index = 0; index + 8 <= bits.length; index += 8) {
    bytes.push(Number.parseInt(bits.slice(index, index + 8), 2));
  }
  return Buffer.from(bytes);
}

async function readBundledAppHtml(extensionUri: vscode.Uri): Promise<string | undefined> {
  const appIndexPath = vscode.Uri.joinPath(extensionUri, "media", "app", "index.html").fsPath;
  try {
    return await fs.readFile(appIndexPath, "utf8");
  } catch (error) {
    if (isFileNotFound(error)) {
      outputChannel?.appendLine("Bundled OpenMates web app not found; using bootstrap shell.");
      return undefined;
    }
    throw error;
  }
}

function resolveBundledAssetUri(webview: vscode.Webview, extensionUri: vscode.Uri, assetPath: string): string {
  const safeSegments = getSafeBundledAssetSegments(assetPath);
  return webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "media", "app", ...safeSegments)).toString();
}

function isFileNotFound(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && (error as NodeJS.ErrnoException).code === "ENOENT";
}

function showRemoteAccessSetup(): void {
  vscode.window.showInformationMessage(
    "Install and start the OpenMates CLI on the machine that has the project files: openmates login && openmates remote-access start --path ./my-project",
  );
}

function resolveWorkspaceFile(relativePath: string, sourceId?: string): vscode.Uri | null {
  if (path.isAbsolute(relativePath) || relativePath.includes("\0") || relativePath.split(/[\\/]/).includes("..")) {
    return null;
  }
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) return null;
  if (sourceId && !workspaceMatchesSource(workspaceFolder, sourceId)) return null;
  return vscode.Uri.joinPath(workspaceFolder.uri, ...relativePath.split(/[\\/]/).filter(Boolean));
}

function workspaceMatchesSource(workspaceFolder: vscode.WorkspaceFolder, sourceId: string): boolean {
  const workspaceName = workspaceFolder.name.toLowerCase();
  const workspaceBaseName = path.basename(workspaceFolder.uri.fsPath).toLowerCase();
  const normalizedSource = sourceId.toLowerCase();
  return normalizedSource === workspaceName || normalizedSource === workspaceBaseName;
}

function inferLanguage(filePath: string): string {
  const extension = path.extname(filePath).replace(/^\./, "");
  return extension || "plaintext";
}
