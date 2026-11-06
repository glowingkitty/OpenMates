// Page end of the shared Rust core Worker's `crypto` unit as a WebCryptoEndpoint.
// Opens the namespace port (pre-bind: works logged out), buffers batches sent
// before the port is ready, and reports one failure when the open is refused
// or the shared Worker crashes. The client then opens a fresh unit on its next
// call; there is no TypeScript fallback.
import type { SharedRustCore } from '../host/sharedCoreRegistry';
import type { WebCryptoBatch, WebCryptoEndpoint, WebCryptoReplies } from './webCryptoClient';

export function createSharedCryptoEndpoint(core: SharedRustCore): WebCryptoEndpoint {
  let port: MessagePort | null = null;
  let closed = false;
  let buffered: WebCryptoBatch[] = [];
  const replyListeners: ((replies: WebCryptoReplies) => void)[] = [];
  const failureListeners: ((error: Error) => void)[] = [];
  let failed = false;

  const fail = (error: Error) => {
    if (failed || closed) return;
    failed = true;
    buffered = [];
    for (const listener of failureListeners) listener(error);
  };
  const stopCrashWatch = core.onCrash(() => fail(new Error('shared_core_crashed')));

  core.openUnit('crypto').then(
    (opened) => {
      if (closed || failed) {
        opened.close();
        return;
      }
      port = opened;
      opened.onmessage = (event: MessageEvent<WebCryptoReplies>) => {
        for (const listener of replyListeners) listener(event.data);
      };
      opened.onmessageerror = () => fail(new Error('rust_web_crypto_bad_reply'));
      opened.start();
      for (const batch of buffered.splice(0)) opened.postMessage(batch);
    },
    (error: unknown) => fail(error instanceof Error ? error : new Error('rust_web_crypto_open_failed')),
  );

  return {
    send(batch) {
      if (closed || failed) return;
      if (port) port.postMessage(batch);
      else buffered.push(batch);
    },
    onReplies(listener) { replyListeners.push(listener); },
    onFailure(listener) { failureListeners.push(listener); },
    close() {
      if (closed) return;
      closed = true;
      buffered = [];
      stopCrashWatch();
      if (port) {
        port.onmessage = null;
        port.close();
      }
    },
  };
}
