/*
 * OpenMates VS Code webview bootstrap.
 *
 * Purpose: provide a tiny startup bridge until the shared Svelte app bundle is
 * emitted into this webview target.
 * Architecture: the real app bundle will reuse the same config element and
 * message channel.
 * Security: V1 sends only readiness metadata and exposes no mutation commands.
 */

const vscode = acquireVsCodeApi();
const configElement = document.getElementById("openmates-vscode-config");
const config = configElement ? JSON.parse(configElement.textContent || "{}") : {};
const SMOKE_LOGIN_TIMEOUT_MS = 40000;

document.body.dataset.openmatesLoginMode = config.loginMode || "pair_only";
vscode.postMessage({ type: "reportReady" });

if (config.smokeLogin) {
  runSmokeLogin().then(
    (result) => vscode.postMessage({ type: "loginSmokeResult", ok: true, ...result }),
    (error) => vscode.postMessage({ type: "loginSmokeResult", ok: false, error: error instanceof Error ? error.message : String(error) }),
  );
}

async function runSmokeLogin() {
  const result = await requestNativeSmokeLogin();
  document.body.dataset.openmatesSmokeAuthenticated = "true";
  return result;
}

function requestNativeSmokeLogin() {
  return new Promise((resolve, reject) => {
    const requestId = crypto.randomUUID();
    const timeout = setTimeout(() => {
      window.removeEventListener("message", onMessage);
      reject(new Error("native_login_smoke_timeout"));
    }, SMOKE_LOGIN_TIMEOUT_MS);

    function onMessage(event) {
      const message = event.data;
      if (!message || message.type !== "loginSmokeNativeResult" || message.requestId !== requestId) return;
      clearTimeout(timeout);
      window.removeEventListener("message", onMessage);
      if (message.ok) {
        resolve({ userId: message.userId || null });
      } else {
        reject(new Error(message.error || "native_login_smoke_failed"));
      }
    }

    window.addEventListener("message", onMessage);
    vscode.postMessage({ type: "loginSmokeNativeRequest", requestId });
  });
}
