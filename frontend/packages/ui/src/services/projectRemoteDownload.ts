import {
  ProjectRemoteAccessError,
  requestProjectRemoteAccess,
  type ProjectRemoteAccessContext,
  type ProjectRemoteFileChunkResult,
  type ProjectSourceViewModel,
  type ProjectViewModel,
} from './projectService';

const CHUNK_BYTES = 128 * 1024;
// Used only when neither the save picker nor OPFS can stream to storage.
const MEMORY_FALLBACK_BYTES = 32 * 1024 * 1024;
const RATE_LIMIT_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 32_000, 32_000];
// The browser can keep reading an OPFS-backed File after its tab closes and
// releases the Web Lock. Keep every temporary file past the save handoff.
const TEMP_GRACE_MS = 2 * 60 * 60_000;
const TEMP_LOCK_PREFIX = 'openmates-connected-download:';
const CLEANUP_INTERVAL_MS = 10 * 60_000;
let cleanupMonitorInstalled = false;

type WritableFile = Pick<FileSystemWritableFileStream, 'write' | 'close' | 'abort'>;
type DownloadSink = {
  write(bytes: Uint8Array): Promise<void>;
  finish(): Promise<void>;
  abort(): Promise<void>;
};

function abortError(): DOMException {
  return new DOMException('Download cancelled', 'AbortError');
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortError();
}

function filenameForPath(path: string): string {
  const basename = path.split(/[\\/]/).filter(Boolean).pop() || 'download';
  return Array.from(basename, (character) => {
    const code = character.charCodeAt(0);
    return code < 32 || code === 127 || (code >= 0x202a && code <= 0x202e)
      || (code >= 0x2066 && code <= 0x2069) || '<>:"/\\|?*'.includes(character) ? '_' : character;
  }).join('').trim().slice(0, 255) || 'download';
}

function offerFile(file: Blob, filename: string, afterOffer?: () => void): void {
  const url = URL.createObjectURL(file);
  try {
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.style.display = 'none';
    document.body.appendChild(anchor);
    try {
      anchor.click();
    } finally {
      anchor.remove();
    }
  } catch (error) {
    URL.revokeObjectURL(url);
    throw error;
  }
  // The anchor click hands a File to the browser asynchronously. Keep its
  // backing OPFS entry until even slow large-file saves have finished reading.
  setTimeout(() => {
    URL.revokeObjectURL(url);
    afterOffer?.();
  }, 60 * 60_000);
}

function tempEntryTimestamp(name: string): { timestamp: number; leased: boolean } | null {
  const match = /^openmates-download-(v2-)?(\d+)-[0-9a-f-]{36}$/.exec(name);
  if (!match) return null;
  const timestamp = Number(match[2]);
  return Number.isSafeInteger(timestamp) ? { timestamp, leased: Boolean(match[1]) } : null;
}

async function sweepTemporaryDownloads(root: FileSystemDirectoryHandle): Promise<void> {
  const iterableRoot = root as FileSystemDirectoryHandle & {
    entries?: () => AsyncIterable<[string, FileSystemHandle]>;
  };
  if (!iterableRoot.entries) return;
  for await (const [name, handle] of iterableRoot.entries()) {
    if (handle.kind !== 'file') continue;
    const entry = tempEntryTimestamp(name);
    if (!entry) continue;
    // A browser save may outlive the tab and its Web Lock. The two-hour grace
    // also protects older tabs that did not acquire a lock at all.
    if (Date.now() - entry.timestamp <= TEMP_GRACE_MS) continue;
    if (!entry.leased || !navigator.locks?.request) {
      await root.removeEntry(name).catch(() => {});
      continue;
    }
    await navigator.locks.request(`${TEMP_LOCK_PREFIX}${name}`, { ifAvailable: true }, async (lock) => {
      if (lock) await root.removeEntry(name).catch(() => {});
    });
  }
}

/** Remove abandoned plaintext download staging files when Projects opens. */
export async function cleanupStaleConnectedProjectDownloads(): Promise<void> {
  if (!cleanupMonitorInstalled && typeof document !== 'undefined') {
    cleanupMonitorInstalled = true;
    setInterval(() => { void cleanupStaleConnectedProjectDownloads(); }, CLEANUP_INTERVAL_MS);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') void cleanupStaleConnectedProjectDownloads();
    });
  }
  if (!navigator.storage?.getDirectory) return;
  try {
    await sweepTemporaryDownloads(await navigator.storage.getDirectory());
  } catch {
    // Storage can be disabled or unavailable in a private browser session.
  }
}

async function acquireTemporaryDownloadLease(name: string): Promise<() => void> {
  if (!navigator.locks?.request) return () => {};
  let releaseLock: (() => void) | undefined;
  let readyResolve: (() => void) | undefined;
  let readyReject: ((error: unknown) => void) | undefined;
  const ready = new Promise<void>((resolve, reject) => {
    readyResolve = resolve;
    readyReject = reject;
  });
  const held = navigator.locks.request(`${TEMP_LOCK_PREFIX}${name}`, async () => {
    await new Promise<void>((resolve) => {
      releaseLock = resolve;
      readyResolve?.();
    });
  });
  void held.catch((error) => readyReject?.(error));
  await ready;
  return () => {
    releaseLock?.();
    releaseLock = undefined;
  };
}

function writableSink(writable: WritableFile): DownloadSink {
  let finished = false;
  return {
    async write(bytes) { await writable.write(bytes as Uint8Array<ArrayBuffer>); },
    async finish() {
      await writable.close();
      finished = true;
    },
    async abort() {
      if (!finished) await writable.abort().catch(() => {});
    },
  };
}

async function createOpfsSink(filename: string): Promise<DownloadSink | null> {
  if (!navigator.storage?.getDirectory) return null;
  const root = await navigator.storage.getDirectory();
  await sweepTemporaryDownloads(root);
  const tempName = `openmates-download-v2-${Date.now()}-${crypto.randomUUID()}`;
  const releaseLease = await acquireTemporaryDownloadLease(tempName);
  let writable: FileSystemWritableFileStream;
  let handle: FileSystemFileHandle;
  try {
    handle = await root.getFileHandle(tempName, { create: true });
    if (typeof handle.createWritable !== 'function') {
      await root.removeEntry(tempName).catch(() => {});
      releaseLease();
      return null;
    }
    writable = await handle.createWritable();
  } catch (error) {
    await root.removeEntry(tempName).catch(() => {});
    releaseLease();
    throw error;
  }
  let finished = false;
  return {
    async write(bytes) { await writable.write(bytes as Uint8Array<ArrayBuffer>); },
    async finish() {
      await writable.close();
      finished = true;
      const file = await handle.getFile();
      offerFile(file, filename, () => {
        void root.removeEntry(tempName).catch(() => {}).finally(releaseLease);
      });
    },
    async abort() {
      if (!finished) await writable.abort().catch(() => {});
      await root.removeEntry(tempName).catch(() => {}).finally(releaseLease);
    },
  };
}

function createMemorySink(filename: string): DownloadSink {
  const chunks: BlobPart[] = [];
  let length = 0;
  return {
    async write(bytes) {
      if (length + bytes.length > MEMORY_FALLBACK_BYTES) {
        throw new Error('This browser cannot save a file this large. Use a browser with local file storage support.');
      }
      chunks.push(bytes.slice());
      length += bytes.length;
    },
    async finish() { offerFile(new Blob(chunks, { type: 'application/octet-stream' }), filename); },
    async abort() { chunks.length = 0; },
  };
}

async function createSink(filename: string, pickerPromise?: Promise<FileSystemFileHandle>): Promise<DownloadSink> {
  if (pickerPromise) return writableSink(await (await pickerPromise).createWritable());
  try {
    const opfs = await createOpfsSink(filename);
    if (opfs) return opfs;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'QuotaExceededError') {
      throw new Error('There is not enough browser storage to download this connected file');
    }
    if (error instanceof DOMException && error.name === 'NotSupportedError') return createMemorySink(filename);
    throw error;
  }
  return createMemorySink(filename);
}

function waitForRetry(delayMs: number, signal?: AbortSignal): Promise<void> {
  throwIfAborted(signal);
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, delayMs);
    const onAbort = () => {
      clearTimeout(timeout);
      reject(abortError());
    };
    signal?.addEventListener('abort', onAbort, { once: true });
    if (signal?.aborted) onAbort();
  });
}

async function requestChunk(
  project: ProjectViewModel,
  source: ProjectSourceViewModel,
  context: ProjectRemoteAccessContext,
  path: string,
  offset: number,
  signal?: AbortSignal,
): Promise<ProjectRemoteFileChunkResult> {
  let retries = 0;
  for (;;) {
    throwIfAborted(signal);
    try {
      return await requestProjectRemoteAccess<ProjectRemoteFileChunkResult>(
        project, source, context, 'read_file_chunk', { path, offset }, signal,
      );
    } catch (error) {
      if (!(error instanceof ProjectRemoteAccessError)
        || !['rate_limited', 'request_rate_limited'].includes(error.code)
        || retries >= RATE_LIMIT_DELAYS_MS.length) throw error;
      await waitForRetry(RATE_LIMIT_DELAYS_MS[retries++], signal);
    }
  }
}

/** Save verified source chunks without accumulating the whole file in JS memory. */
export async function downloadConnectedProjectFile(
  project: ProjectViewModel,
  source: ProjectSourceViewModel,
  context: ProjectRemoteAccessContext,
  path: string,
  signal?: AbortSignal,
  onProgress?: (downloadedBytes: number, totalBytes: number) => void,
): Promise<void> {
  const filename = filenameForPath(path);
  const pickerWindow = window as Window & {
    showSaveFilePicker?: (options: { suggestedName: string }) => Promise<FileSystemFileHandle>;
  };
  // Invoke this before the first await so the browser retains the click's user activation.
  const pickerPromise = pickerWindow.showSaveFilePicker?.({ suggestedName: filename });
  const sink = await createSink(filename, pickerPromise);
  let total: number | undefined;
  let expectedIdentity: string | undefined;
  let offset = 0;
  try {
    do {
      throwIfAborted(signal);
      const result = await requestChunk(project, source, context, path, offset, signal);
      if (!Number.isSafeInteger(result.size_bytes) || result.size_bytes < 0
        || result.offset !== offset || (total !== undefined
        && (result.size_bytes !== total || result.file_identity !== expectedIdentity))) {
        throw new Error('The connected file changed during download');
      }
      const bytes = Uint8Array.from(atob(result.content_base64), (character) => character.charCodeAt(0));
      const expectedLength = Math.min(CHUNK_BYTES, result.size_bytes - offset);
      if (bytes.length !== expectedLength) throw new Error('The connected source returned an incomplete file chunk');
      const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
      const hash = Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('');
      if (hash !== result.chunk_hash) throw new Error('The connected source returned a corrupt file chunk');
      throwIfAborted(signal);
      await sink.write(bytes);
      offset += bytes.length;
      total = result.size_bytes;
      expectedIdentity = result.file_identity;
      onProgress?.(offset, total);
    } while (offset < total);
    if (offset !== total) throw new Error('The connected file download is incomplete');
    throwIfAborted(signal);
    await sink.finish();
  } catch (error) {
    await sink.abort();
    if (error instanceof DOMException && error.name === 'QuotaExceededError') {
      throw new Error('There is not enough storage to download this connected file');
    }
    throw error;
  }
}
