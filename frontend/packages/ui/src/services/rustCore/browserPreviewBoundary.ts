/// <reference lib="es2022.object" />
/** Isolated preview proof transport only; never an application bundle resolver. */
export interface PreviewBootstrap {
  version: 1;
  operation: "bootstrap";
  artifact: string;
  apiUrl: string;
  appOrigin: string;
  sessionId: string;
  expectedPrincipal: string;
  priorPrincipal: string;
}

/** Inactive fresh admission carries no prior profile owner or credential. */
export interface PasswordPreviewBootstrap {
  version:1; operation:"bootstrap_password"; artifact:string;
  apiUrl:string;appOrigin:string;sessionId:string;
}
export function validPasswordBootstrap(value:unknown,actualOrigin:string):value is PasswordPreviewBootstrap {
  if(typeof value!=="object"||value===null||Object.getPrototypeOf(value)!==Object.prototype)return false;
  const data=value as Record<string,unknown>;
  const keys=["version","operation","artifact","apiUrl","appOrigin","sessionId"];
  if(Object.keys(data).length!==keys.length||!Object.keys(data).every(key=>keys.includes(key))
    ||data.version!==1||data.operation!=="bootstrap_password"||data.appOrigin!==actualOrigin
    ||typeof data.artifact!=="string"||typeof data.apiUrl!=="string"||data.apiUrl.length>256
    ||typeof data.sessionId!=="string"||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(data.sessionId))return false;
  try {
    previewAssets(actualOrigin,data.artifact);const api=new URL(data.apiUrl);
    return api.protocol==="http:"&&["localhost","127.0.0.1"].includes(api.hostname)
      &&!api.username&&!api.password&&api.pathname==="/"&&!api.search&&!api.hash
      &&[api.origin,`${api.origin}/`].includes(data.apiUrl)
      &&!data.apiUrl.includes("@")&&!data.apiUrl.includes("?")&&!data.apiUrl.includes("#");
  } catch {return false;}
}

/** Explicit existing-key proof has no witness or invented owner authority. */
export interface ExistingKeyPreviewBootstrap extends Omit<PasswordPreviewBootstrap,"operation"> {operation:"bootstrap_existing_key";expectedPrincipal:string}
export function validExistingKeyBootstrap(value:unknown,actualOrigin:string):value is ExistingKeyPreviewBootstrap {
  if(typeof value!=="object"||value===null||Object.getPrototypeOf(value)!==Object.prototype
    ||(value as Record<string,unknown>).operation!=="bootstrap_existing_key")return false;
  const data=value as Record<string,unknown>;
  if(Reflect.ownKeys(data).length!==7||typeof data.expectedPrincipal!=="string"
    ||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(data.expectedPrincipal))return false;
  const {expectedPrincipal,...base}=data;void expectedPrincipal;
  return validPasswordBootstrap({...base,operation:"bootstrap_password"},actualOrigin);
}
export function waitForExistingKeyPreviewWorker(worker:Worker,bootstrap:ExistingKeyPreviewBootstrap,signal:AbortSignal):Promise<void>{
  return waitForWorkerReady(worker,bootstrap,signal,[]);
}

export function previewAssets(origin: string, artifact: string): { javascript: string; wasm: string } {
  const app = new URL(origin);
  if (app.origin !== origin || app.protocol !== "http:" || !["localhost", "127.0.0.1"].includes(app.hostname)
    || !/^[a-f0-9]{64}$/.test(artifact)) throw new Error("invalid_request");
  const base = `${origin}/__ci/rust-core/${artifact}/`;
  return { javascript: `${base}openmates_browser.js`, wasm: `${base}openmates_browser_bg.wasm` };
}

export function validBootstrap(value: unknown, actualOrigin: string): value is PreviewBootstrap {
  if (typeof value !== "object" || value === null || Object.getPrototypeOf(value) !== Object.prototype) return false;
  const data = value as Record<string, unknown>;
  const keys = ["version", "operation", "artifact", "apiUrl", "appOrigin", "sessionId", "expectedPrincipal", "priorPrincipal"];
  if (Object.keys(data).length !== keys.length || !Object.keys(data).every((key) => keys.includes(key))
    || data.version !== 1 || data.operation !== "bootstrap" || data.appOrigin !== actualOrigin
    || typeof data.artifact !== "string" || typeof data.apiUrl !== "string" || data.apiUrl.length > 256
    || ![data.sessionId, data.expectedPrincipal, data.priorPrincipal].every((value) => typeof value === "string"
      && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value))) return false;
  try {
    previewAssets(actualOrigin, data.artifact);
    const api = new URL(data.apiUrl);
    return api.protocol === "http:" && ["localhost", "127.0.0.1"].includes(api.hostname)
      && !api.username && !api.password && api.pathname === "/" && !api.search && !api.hash
      && [api.origin, `${api.origin}/`].includes(data.apiUrl)
      && !data.apiUrl.includes("@") && !data.apiUrl.includes("?") && !data.apiUrl.includes("#");
  } catch { return false; }
}

/** Construct Host only after this finite ready message; Host rejects unsolicited replies. */
export function waitForPreviewWorker(worker: Worker, bootstrap: PreviewBootstrap, signal: AbortSignal, witnessPort: MessagePort): Promise<void> {
  return waitForWorkerReady(worker,bootstrap,signal,[witnessPort]);
}
export function waitForPasswordPreviewWorker(worker:Worker,bootstrap:PasswordPreviewBootstrap,signal:AbortSignal):Promise<void> {
  return waitForWorkerReady(worker,bootstrap,signal,[]);
}
function waitForWorkerReady(worker:Worker,bootstrap:PreviewBootstrap|PasswordPreviewBootstrap|ExistingKeyPreviewBootstrap,signal:AbortSignal,ports:MessagePort[]):Promise<void> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error: string | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      worker.removeEventListener("message", receive);
      worker.removeEventListener("messageerror", fail);
      worker.removeEventListener("error", fail);
      signal.removeEventListener("abort", abort);
      if (error) { worker.terminate(); reject(new Error(error)); } else resolve();
    };
    const receive = (event: MessageEvent<unknown>) => {
      const data = event.data;
      if (typeof data === "object" && data !== null && Object.keys(data).length === 2
        && "version" in data && data.version === 1 && "ready" in data && data.ready === true) finish(null);
      else finish("unavailable");
    };
    const fail = () => finish("unavailable");
    const abort = () => finish("cancelled");
    const timer = setTimeout(() => finish("deadline"), 30_000);
    worker.addEventListener("message", receive);
    worker.addEventListener("messageerror", fail);
    worker.addEventListener("error", fail);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
    else { try { worker.postMessage(bootstrap, ports); } catch { fail(); } }
  });
}

export interface SessionWitness {
  captureComplete: boolean;
  sessionSucceeded: boolean;
  expectedOwnerMatched: boolean;
  priorOwnerDifferent: boolean;
  expectedPrincipalRejected: boolean;
}
export function validSessionWitness(value: unknown): value is SessionWitness {
  const keys = ["captureComplete", "sessionSucceeded", "expectedOwnerMatched", "priorOwnerDifferent", "expectedPrincipalRejected"];
  return typeof value === "object" && value !== null && Object.getPrototypeOf(value) === Object.prototype
    && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)
      && typeof (value as Record<string, unknown>)[key] === "boolean");
}

/** Test-only passive Worker observer. Original fetch arguments/response are
 * returned unchanged; no auth response, ID or token leaves this Worker.
 */
export function observePreviewSessionFetch(scope: { fetch: typeof fetch }, configuration: PreviewBootstrap,
  publish: (witness: SessionWitness) => void): () => void {
  const original = scope.fetch;
  let observed = false;
  let disposed = false;
  const endpoint = new URL("/v1/auth/session", configuration.apiUrl).href;
  const unknown: SessionWitness = { captureComplete: false, sessionSucceeded: false, expectedOwnerMatched: false, priorOwnerDifferent: false, expectedPrincipalRejected: false };
  const project = async (response: Response): Promise<SessionWitness> => {
    if (response.status !== 200 && response.status !== 403) return { ...unknown, captureComplete: true };
    const clone = response.clone();
    const reader = clone.body?.getReader();
    if (!reader) return unknown;
    const chunks: Uint8Array[] = [];
    let combined: Uint8Array | null = null;
    let size = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("capture_deadline")), 1000); });
    try {
      for (;;) {
        const part = await Promise.race([reader.read(), deadline]);
        if (part.done) break;
        size += part.value.byteLength;
        if (size > 64 * 1024) return unknown;
        // Own copies only: never erase a tee chunk that might alias the SDK's
        // original response stream in an implementation's clone machinery.
        chunks.push(new Uint8Array(part.value));
      }
      combined = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { combined.set(chunk, offset); offset += chunk.byteLength; }
      const body = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(combined));
      if(response.status===403){
        const rejected=body&&Object.getPrototypeOf(body)===Object.prototype&&Object.keys(body).length===1
          &&body.detail&&Object.getPrototypeOf(body.detail)===Object.prototype&&Object.keys(body.detail).length===1
          &&body.detail.error==="session_principal_mismatch";
        return {...unknown,captureComplete:true,expectedPrincipalRejected:Boolean(rejected)};
      }
      const principal = body?.user?.id;
      const succeeded = body?.success === true && typeof principal === "string"
        && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(principal);
      return { captureComplete: true, sessionSucceeded: succeeded,
        expectedOwnerMatched: succeeded && principal === configuration.expectedPrincipal,
        priorOwnerDifferent: succeeded && principal !== configuration.priorPrincipal, expectedPrincipalRejected: false };
    } catch { return unknown; }
    finally {
      if (timer !== undefined) clearTimeout(timer);
      void reader.cancel().catch(() => undefined);
      for (const chunk of chunks) chunk.fill(0);
      combined?.fill(0);
    }
  };
  const wrapped: typeof fetch = async (...args) => {
    const response = await Reflect.apply(original, scope, args);
    try {
      const [input, init] = args;
      const request = input instanceof Request ? input : null;
      const url = request ? request.url : String(input);
      const method = init?.method ?? request?.method ?? "GET";
      const headers = new Headers(init?.headers ?? request?.headers);
      if (!disposed && !observed && url === endpoint && method === "POST" && headers.get("X-OpenMates-SDK") === "rust") {
        observed = true;
        void project(response).then((witness) => { if (!disposed) publish(witness); }).catch(() => undefined);
      }
    } catch { /* Observation cannot change fetch success/failure or SDK parsing. */ }
    return response;
  };
  scope.fetch = wrapped;
  return () => { disposed = true; if (scope.fetch === wrapped) scope.fetch = original; };
}
