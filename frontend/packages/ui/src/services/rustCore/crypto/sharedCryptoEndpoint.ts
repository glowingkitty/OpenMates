// Page end of the shared Rust core Worker's `crypto` unit as a WebCryptoEndpoint.
// Opens the namespace port (pre-bind: works logged out), buffers batches sent
// before the port is ready, and reports one failure when the open is refused
// or the shared Worker stops: `shared_core_crashed` when it failed,
// `shared_core_terminated` when it was stopped on purpose (idle retirement,
// logout). The client then opens a fresh unit on its next call; there is no
// TypeScript fallback.
import type { SharedRustCore } from '../host/sharedCoreRegistry';
import { SHARED_CORE_TERMINATED, type WebCryptoBatch, type WebCryptoEndpoint, type WebCryptoReplies } from './webCryptoClient';

export function createSharedCryptoEndpoint(core: SharedRustCore): WebCryptoEndpoint {
  let port: MessagePort | null = null;
  let closed = false;
  let buffered: WebCryptoBatch[] = [];
  const replyListeners: ((replies: WebCryptoReplies) => void)[] = [];
  const failureListeners: ((error: Error) => void)[] = [];
  let failed = false;
  // Requests sent and not yet answered keep the realm from idle retirement.
  let outstanding = 0;
  let release: (() => void) | null = null;
  const settleOutstanding = (count: number | null) => {
    outstanding = count === null ? 0 : Math.max(0, outstanding - count);
    if (outstanding === 0 && release) { release(); release = null; }
  };

  const fail = (error: Error) => {
    if (failed || closed) return;
    failed = true;
    buffered = [];
    settleOutstanding(null);
    for (const listener of failureListeners) listener(error);
  };
  const stopCrashWatch = core.onCrash((stop) =>
    fail(new Error(stop === 'terminated' ? SHARED_CORE_TERMINATED : 'shared_core_crashed')));

  core.openUnit('crypto').then(
    (opened) => {
      if (closed || failed) {
        opened.close();
        return;
      }
      port = opened;
      opened.onmessage = (event: MessageEvent<WebCryptoReplies>) => {
        settleOutstanding(event.data?.responses?.length ?? 0);
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
      if (batch.requests.length > 0) {
        release ??= core.hold();
        outstanding += batch.requests.length;
      }
      if (port) port.postMessage(batch);
      else buffered.push(batch);
    },
    onReplies(listener) { replyListeners.push(listener); },
    onFailure(listener) { failureListeners.push(listener); },
    close() {
      if (closed) return;
      closed = true;
      buffered = [];
      settleOutstanding(null);
      stopCrashWatch();
      if (port) {
        port.onmessage = null;
        port.close();
      }
    },
  };
}
