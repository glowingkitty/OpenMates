// Verify that IndexedDB and WebCrypto results remain in their original scope.
import { expect, it, vi } from "vitest";
import { invalidateWorkspaceCaches } from "../../workspaceCacheLifecycle";
import { ChatKeyManager } from "../ChatKeyManager";

vi.mock("../../cryptoService", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  decryptChatKeyWithMasterKey: vi.fn(),
}));

// contract-test: direct surface=gui.web assertions=auth.secrets.lifecycle
it("discards an old workspace unwrap without removing the new load", async () => {
  const mgr = new ChatKeyManager();
  const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
  let finishOld!: (value: Uint8Array) => void;
  let finishCurrent!: (value: Uint8Array) => void;
  const oldKey = new Uint8Array(32).fill(31);
  const currentKey = new Uint8Array(32).fill(42);
  vi.mocked(decryptChatKeyWithMasterKey)
    .mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; }))
    .mockImplementationOnce(() => new Promise(resolve => { finishCurrent = resolve; }));
  const fetcher = vi.fn().mockResolvedValue("encrypted-key");
  mgr.setEncryptedChatKeyFetcher(fetcher);

  const older = mgr.getKey("chat-1");
  await vi.waitFor(() => expect(finishOld).toBeTypeOf("function"));
  invalidateWorkspaceCaches();
  const current = mgr.getKey("chat-1");
  await vi.waitFor(() => expect(finishCurrent).toBeTypeOf("function"));

  finishOld(oldKey);
  expect(await older).toBeNull();
  expect(mgr.getKeySync("chat-1")).toBeNull();

  const joined = mgr.getKey("chat-1");
  finishCurrent(currentKey);
  expect(await current).toEqual(currentKey);
  expect(await joined).toEqual(currentKey);
  expect(fetcher).toHaveBeenCalledTimes(2);
});


// contract-test: direct surface=gui.web assertions=auth.secrets.lifecycle
it("does not publish a server key when its unwrap outlives the workspace", async () => {
  const mgr = new ChatKeyManager();
  const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
  let finish!: (value: Uint8Array) => void;
  vi.mocked(decryptChatKeyWithMasterKey).mockImplementationOnce(
    () => new Promise(resolve => { finish = resolve; }),
  );
  const onReady = vi.fn();
  mgr.onKeyReady(onReady);

  const receipt = mgr.receiveKeyFromServer("old-chat", "server-wrapper");
  invalidateWorkspaceCaches();
  finish(new Uint8Array(32).fill(7));

  expect(await receipt).toBeNull();
  expect(mgr.getKeySync("old-chat")).toBeNull();
  expect(onReady).not.toHaveBeenCalled();
});

// contract-test: direct surface=gui.web assertions=auth.secrets.lifecycle
it("does not promote or persist a server key when its local read outlives sign-out", async () => {
  const mgr = new ChatKeyManager();
  const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
  vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValueOnce(new Uint8Array(32).fill(7));
  let finish!: (value: string) => void;
  mgr.setEncryptedChatKeyFetcher(() => new Promise(resolve => { finish = resolve; }));
  const persistPrimary = vi.fn();
  const persistCandidate = vi.fn();
  mgr.setEncryptedChatKeyPersister(persistPrimary);
  mgr.setCandidateKeyPersister(persistCandidate);

  const acceptance = mgr.acceptServerKeyForMismatch("old-chat", "server-wrapper");
  await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
  mgr.clearAll({ broadcast: false });
  finish("local-wrapper");

  expect(await acceptance).toBeNull();
  expect(mgr.getKeySync("old-chat")).toBeNull();
  expect(persistPrimary).not.toHaveBeenCalled();
  expect(persistCandidate).not.toHaveBeenCalled();
});
