/// <reference lib="webworker" />
import { artifact, loadBinding } from 'virtual:openmates-rust-core-package';
import { validProductionBootstrap } from './productionBootstrap';
import { installBrowserCoreWorker } from '@openmates/ui/src/services/rustCore/workerRuntime';
import type { BrowserCoreBinding, WorkerEndpoint, RustRecoveryBootstrap, RustInitialSyncStoreBootstrap } from '@openmates/ui/src/services/rustCore/workerRuntime';

// Separate production asset entry; existing CI proof entry stays unchanged.
// Importing this bundle performs no admission, account read or credential IO.
const scope = self as DedicatedWorkerGlobalScope;
let started = false;
scope.addEventListener('message', async function bootstrap(event: MessageEvent<unknown>) {
  if (started) return;
  started = true; scope.removeEventListener('message',bootstrap);
  const configuration = event.data;
  if (!scope.isSecureContext || event.ports.length > 1
    || !validProductionBootstrap(configuration,scope.location.origin,artifact)) { scope.close(); return; }
  try {
    const generated = await loadBinding() as BrowserCoreBinding;
    if (typeof generated.PreparedBrowserProfile?.from_existing_key !== 'function') throw Error('unavailable');
    let recovery:RustRecoveryBootstrap|undefined;
    if(event.ports.length===1){
      const capture=generated.capture_original_recovery_bootstrap;
      if(typeof capture!=='function')throw Error('unavailable');
      recovery=capture(event);if(!recovery)throw Error('unavailable');
    }
    // Feature-only export captures this SAME original trusted native event.
    // It is never reconstructed from frame data or admitted after Client escape.
    let startup:RustInitialSyncStoreBootstrap|undefined;
    if(typeof generated.capture_initial_sync_store==='function'){if(!recovery)throw Error('unavailable');startup=generated.capture_initial_sync_store(event);}
    installBrowserCoreWorker(scope as unknown as WorkerEndpoint,generated,
      {apiUrl:configuration.apiUrl,appOrigin:configuration.appOrigin,sessionId:configuration.sessionId,
        admission:'existing_key',expectedPrincipal:configuration.expectedPrincipal},scope.navigator.locks,recovery,startup);
    scope.postMessage({version:1,ready:true});
  } catch {
    scope.postMessage({version:1,ready:false}); scope.close();
  }
});
