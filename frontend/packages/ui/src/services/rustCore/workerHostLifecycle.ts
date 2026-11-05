// Page lifecycle binding for BrowserCoreWorkerHost, split from workerHost.ts.
import type {BrowserCoreWorkerHost} from "./workerHost";

/** Explicit opt-in only; no import-time activation or dependency on existing stores. */
export function bindPageLifecycle(host: BrowserCoreWorkerHost, page: Window, channel: BroadcastChannel): () => void {
  const close = () => host.close();
  const invalidate = (event: MessageEvent<unknown>) => {
    const data = event.data;
    if (typeof data === "object" && data !== null && Object.keys(data).length === 2
      && "version" in data && data.version === 1 && "type" in data && data.type === "invalidate") close();
  };
  page.addEventListener("pagehide", close);
  channel.addEventListener("message", invalidate);
  return () => {
    page.removeEventListener("pagehide", close);
    channel.removeEventListener("message", invalidate);
    host.close();
    channel.close();
  };
}
