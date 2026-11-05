/// <reference lib="webworker" />
import { observePreviewSessionFetch,previewAssets,validBootstrap,validExistingKeyBootstrap,validPasswordBootstrap } from "./browserPreviewBoundary";
import type { BrowserCoreBinding,WorkerEndpoint } from "./workerRuntime";
import { installBrowserCoreWorker } from "./workerRuntime";

// Dedicated Worker entry for the opt-in isolated preview proof only. No static
// import of absent generated packages and no native/JS implementation fallback.
const scope = self as unknown as DedicatedWorkerGlobalScope;
let started = false;
scope.addEventListener("message", async function bootstrap(event: MessageEvent<unknown>) {
  if (started) return;
  started = true;
  scope.removeEventListener("message", bootstrap);
  const prior=validBootstrap(event.data,scope.location.origin);
  const fresh=validPasswordBootstrap(event.data,scope.location.origin);
  const existing=validExistingKeyBootstrap(event.data,scope.location.origin);
  if ((!prior&&!fresh&&!existing)||event.ports.length!==(prior?1:0)) {scope.close();return;}
  const configuration=event.data;
  if(!validBootstrap(configuration,scope.location.origin)&&!validPasswordBootstrap(configuration,scope.location.origin)&&!validExistingKeyBootstrap(configuration,scope.location.origin)){scope.close();return;}
  const witnessPort=event.ports[0];
  try {
    const assets = previewAssets(scope.location.origin, configuration.artifact);
    const generated = await import(/* @vite-ignore */ assets.javascript);
    await generated.default({ module_or_path: assets.wasm });
    if(existing&&typeof generated.PreparedBrowserProfile?.from_existing_key!=="function")throw Error("unavailable");
    if(fresh&&typeof generated.BrowserCoreClient?.login_password!=="function")throw Error("unavailable");
    if(validBootstrap(configuration,scope.location.origin)) {
      observePreviewSessionFetch(scope,configuration,(witness)=>witnessPort.postMessage(witness));
    }
    installBrowserCoreWorker(scope as unknown as WorkerEndpoint, generated as BrowserCoreBinding,
      { apiUrl: configuration.apiUrl, appOrigin: configuration.appOrigin, sessionId: configuration.sessionId,admission:fresh?"fresh_password":existing?"existing_key":"prior_profile",
        ...(validExistingKeyBootstrap(configuration,scope.location.origin)?{expectedPrincipal:configuration.expectedPrincipal}:{}) }, scope.navigator.locks);
    scope.postMessage({ version: 1, ready: true });
  } catch {
    // No raw wasm/JS/server exception contents cross this endpoint.
    scope.postMessage({ version: 1, ready: false });
    scope.close();
  }
});
