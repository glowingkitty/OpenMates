import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProjectSourceViewModel, ProjectViewModel } from '../projectService';

const mocks = vi.hoisted(() => ({ requestProjectRemoteAccess: vi.fn() }));
vi.mock('../projectService', () => ({
  requestProjectRemoteAccess: mocks.requestProjectRemoteAccess,
  ProjectRemoteAccessError: class ProjectRemoteAccessError extends Error {
    constructor(public code: string, message: string) { super(message); }
  },
}));

import { cleanupStaleConnectedProjectDownloads, downloadConnectedProjectFile, purgeConnectedProjectDownloadStaging } from '../projectRemoteDownload';

const project = {} as ProjectViewModel;
const source = {} as ProjectSourceViewModel;
const context = { ownerId: 'owner-1' };
const CHUNK_BYTES = 128 * 1024;
const identity = 'a'.repeat(64);

async function chunk(offset: number, size: number, corrupt = false) {
  const bytes = new Uint8Array(Math.min(CHUNK_BYTES, size - offset));
  bytes.fill(65);
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
    (byte) => byte.toString(16).padStart(2, '0')).join('');
  let binary = '';
  for (let index = 0; index < bytes.length; index++) binary += String.fromCharCode(bytes[index]);
  return {
    offset, size_bytes: size, file_identity: identity,
    content_base64: btoa(binary), chunk_hash: corrupt ? '0'.repeat(64) : hash,
  };
}

describe('connected project file download', () => {
  let writes: Uint8Array[];
  let abort: ReturnType<typeof vi.fn>;
  let close: ReturnType<typeof vi.fn>;
  let removeEntry: ReturnType<typeof vi.fn>;
  let clicked: ReturnType<typeof vi.fn<() => void>>;

  beforeEach(() => {
    vi.restoreAllMocks();
    mocks.requestProjectRemoteAccess.mockReset();
    writes = [];
    abort = vi.fn().mockResolvedValue(undefined);
    close = vi.fn().mockResolvedValue(undefined);
    removeEntry = vi.fn().mockResolvedValue(undefined);
    clicked = vi.fn<() => void>();
    const writable = { write: vi.fn(async (bytes: Uint8Array) => { writes.push(bytes.slice()); }), close, abort };
    const fileHandle = { createWritable: vi.fn().mockResolvedValue(writable), getFile: vi.fn().mockResolvedValue(new Blob()) };
    const root = {
      entries: async function* () {},
      getFileHandle: vi.fn().mockResolvedValue(fileHandle), removeEntry,
    };
    Object.defineProperty(navigator, 'storage', { configurable: true, value: { getDirectory: async () => root } });
    Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
    Object.defineProperty(window, 'showSaveFilePicker', { configurable: true, value: undefined });
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:connected-download');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const realCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const element = realCreateElement(tag);
      if (tag === 'a') vi.spyOn(element as HTMLAnchorElement, 'click').mockImplementation(() => { clicked(); });
      return element;
    });
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.connected-embed-previews
  it('streams a file larger than 4 MiB through OPFS and reports verified progress', async () => {
    const size = 4 * 1024 * 1024 + 1;
    mocks.requestProjectRemoteAccess.mockImplementation(async (_project, _source, _context, _operation, args) =>
      chunk(args.offset as number, size));
    const progress = vi.fn();
    await downloadConnectedProjectFile(project, source, context, 'large.bin', undefined, progress);
    expect(writes).toHaveLength(33);
    expect(writes.every((bytes) => bytes.length <= CHUNK_BYTES)).toBe(true);
    expect(writes[writes.length - 1]?.length).toBe(1);
    expect(progress).toHaveBeenLastCalledWith(size, size);
    expect(close).toHaveBeenCalledOnce();
    expect(clicked).toHaveBeenCalledOnce();
    expect(abort).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.connected-embed-previews
  it('aborts and removes the partial file on cancellation', async () => {
    mocks.requestProjectRemoteAccess.mockImplementation(async (_project, _source, _context, _operation, args) =>
      chunk(args.offset as number, 2 * CHUNK_BYTES));
    const controller = new AbortController();
    await expect(downloadConnectedProjectFile(project, source, context, 'cancel.bin', controller.signal,
      () => controller.abort())).rejects.toMatchObject({ name: 'AbortError' });
    expect(writes).toHaveLength(1);
    expect(abort).toHaveBeenCalledOnce();
    expect(removeEntry).toHaveBeenCalledOnce();
    expect(clicked).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.connected-embed-previews
  it('rejects a corrupt chunk before writing or offering the file', async () => {
    mocks.requestProjectRemoteAccess.mockResolvedValue(await chunk(0, CHUNK_BYTES, true));
    await expect(downloadConnectedProjectFile(project, source, context, 'bad.bin'))
      .rejects.toThrow('corrupt file chunk');
    expect(writes).toHaveLength(0);
    expect(abort).toHaveBeenCalledOnce();
    expect(removeEntry).toHaveBeenCalledOnce();
    expect(clicked).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.connected-embed-previews
  it('opens the save picker before the first remote request', async () => {
    const pickerWrites: Uint8Array[] = [];
    const pickerClose = vi.fn().mockResolvedValue(undefined);
    const picker = vi.fn().mockResolvedValue({ createWritable: async () => ({
      write: async (bytes: Uint8Array) => { pickerWrites.push(bytes.slice()); },
      close: pickerClose,
      abort: vi.fn().mockResolvedValue(undefined),
    }) });
    Object.defineProperty(window, 'showSaveFilePicker', { configurable: true, value: picker });
    mocks.requestProjectRemoteAccess.mockImplementation(async (_project, _source, _context, _operation, args) => {
      expect(picker).toHaveBeenCalledWith({ suggestedName: 'picked.bin' });
      return chunk(args.offset as number, 1);
    });
    await downloadConnectedProjectFile(project, source, context, 'picked.bin');
    expect(pickerWrites).toHaveLength(1);
    expect(pickerClose).toHaveBeenCalledOnce();
    expect(clicked).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.connected-embed-previews
  it('cleans an old crashed download while preserving a recent save and an active tab', async () => {
    const oldTimestamp = Date.now() - 3 * 60 * 60_000;
    const crashed = `openmates-download-v2-${oldTimestamp}-11111111-1111-4111-8111-111111111111`;
    const recent = `openmates-download-v2-${Date.now()}-33333333-3333-4333-8333-333333333333`;
    const active = `openmates-download-v2-${oldTimestamp}-22222222-2222-4222-8222-222222222222`;
    const root = {
      entries: async function* () {
        yield [crashed, { kind: 'file' }];
        yield [recent, { kind: 'file' }];
        yield [active, { kind: 'file' }];
      },
      removeEntry: vi.fn().mockResolvedValue(undefined),
    };
    Object.defineProperty(navigator, 'storage', { configurable: true, value: { getDirectory: async () => root } });
    const request = vi.fn(async (name: string, _options: unknown, callback: (lock: object | null) => Promise<void>) =>
      callback(name.endsWith(active) ? null : {}));
    Object.defineProperty(navigator, 'locks', { configurable: true, value: { request } });
    await cleanupStaleConnectedProjectDownloads();
    expect(root.removeEntry).toHaveBeenCalledExactlyOnceWith(crashed);
    expect(request).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.connected-embed-previews
  it('uses a conservative age threshold when cross-tab locks are unavailable', async () => {
    const old = `openmates-download-${Date.now() - 3 * 60 * 60_000}-11111111-1111-4111-8111-111111111111`;
    const recent = `openmates-download-v2-${Date.now()}-22222222-2222-4222-8222-222222222222`;
    const root = {
      entries: async function* () {
        yield [old, { kind: 'file' }];
        yield [recent, { kind: 'file' }];
      },
      removeEntry: vi.fn().mockResolvedValue(undefined),
    };
    Object.defineProperty(navigator, 'storage', { configurable: true, value: { getDirectory: async () => root } });
    await cleanupStaleConnectedProjectDownloads();
    expect(root.removeEntry).toHaveBeenCalledExactlyOnceWith(old);
  });

  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it('purges only app-owned plaintext OPFS staging on logout', async () => {
    const old = `openmates-download-v2-${Date.now() - 1_000}-11111111-1111-4111-8111-111111111111`;
    const unrelated = 'other-app-private-file';
    const root = {
      entries: async function* () {
        yield [old, { kind: 'file' }];
        yield [unrelated, { kind: 'file' }];
      },
      removeEntry: vi.fn().mockResolvedValue(undefined),
    };
    Object.defineProperty(navigator, 'storage', { configurable: true, value: { getDirectory: async () => root } });
    await purgeConnectedProjectDownloadStaging();
    expect(root.removeEntry).toHaveBeenCalledExactlyOnceWith(old);
  });

  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it('aborts an in-flight staged download before logout purge completes', async () => {
    let started!: () => void;
    const requestStarted = new Promise<void>((resolve) => { started = resolve; });
    mocks.requestProjectRemoteAccess.mockImplementation((_project, _source, _context, _op, _args, signal: AbortSignal) => {
      started();
      return new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')), { once: true });
      });
    });
    const download = downloadConnectedProjectFile(project, source, context, 'private.bin');
    const rejected = expect(download).rejects.toMatchObject({ name: 'AbortError' });
    await requestStarted;
    await purgeConnectedProjectDownloadStaging();
    await rejected;
    expect(abort).toHaveBeenCalledOnce();
    expect(removeEntry).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it('does not offer a staged file whose final OPFS read finishes after logout', async () => {
    let fileReady!: () => void;
    let resolveFile!: (file: Blob) => void;
    const readingFile = new Promise<void>((resolve) => { fileReady = resolve; });
    const file = new Promise<Blob>((resolve) => { resolveFile = resolve; });
    const writable = { write: vi.fn().mockResolvedValue(undefined), close, abort };
    const root = {
      entries: async function* () {},
      getFileHandle: vi.fn().mockResolvedValue({
        createWritable: vi.fn().mockResolvedValue(writable),
        getFile: vi.fn(() => { fileReady(); return file; }),
      }),
      removeEntry,
    };
    Object.defineProperty(navigator, 'storage', { configurable: true, value: { getDirectory: async () => root } });
    mocks.requestProjectRemoteAccess.mockResolvedValue(await chunk(0, 1));
    const download = downloadConnectedProjectFile(project, source, context, 'private.bin');
    const rejected = expect(download).rejects.toMatchObject({ name: 'AbortError' });
    await readingFile;
    await purgeConnectedProjectDownloadStaging();
    resolveFile(new Blob());
    await rejected;
    expect(clicked).not.toHaveBeenCalled();
    expect(removeEntry).toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it('retains an already offered browser save until its OPFS handoff releases', async () => {
    vi.useFakeTimers();
    try {
      let stagedName = '';
      const writable = { write: vi.fn().mockResolvedValue(undefined), close, abort };
      const root = {
        entries: async function* () { yield [stagedName, { kind: 'file' }]; },
        getFileHandle: vi.fn(async (name: string) => {
          stagedName = name;
          return { createWritable: async () => writable, getFile: async () => new Blob() };
        }),
        removeEntry,
      };
      Object.defineProperty(navigator, 'storage', { configurable: true, value: { getDirectory: async () => root } });
      mocks.requestProjectRemoteAccess.mockResolvedValue(await chunk(0, 1));
      await downloadConnectedProjectFile(project, source, context, 'offered.bin');
      expect(clicked).toHaveBeenCalledOnce();
      await purgeConnectedProjectDownloadStaging();
      expect(removeEntry).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(60 * 60_000);
      expect(removeEntry).toHaveBeenCalledExactlyOnceWith(stagedName);
    } finally {
      vi.useRealTimers();
    }
  });
});
