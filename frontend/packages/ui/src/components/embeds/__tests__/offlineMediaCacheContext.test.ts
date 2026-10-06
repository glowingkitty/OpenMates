import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  decrypt: vi.fn(),
}));
vi.mock("../../../services/presignedUrlService", () => ({ fetchWithPresignedUrl: mocks.fetch }));
vi.mock("../../../services/encryption/mediaEncryption", () => ({
  decryptMediaPayload: mocks.decrypt,
  MediaEncryptionError: class MediaEncryptionError extends Error {},
}));

import { clearCachedImages, fetchAndDecryptImage } from "../images/imageEmbedCrypto";
import { clearCachedAudio, fetchAndDecryptAudio } from "../audio/audioEmbedCrypto";
import { invalidateWorkspaceCaches } from "../../../services/workspaceCacheLifecycle";

describe("decrypted media cache context boundary", () => {
  beforeEach(() => {
    clearCachedImages();
    clearCachedAudio();
    vi.restoreAllMocks();
    mocks.fetch.mockReset().mockResolvedValue(new ArrayBuffer(4));
    mocks.decrypt.mockReset().mockResolvedValue(new Uint8Array([1, 2, 3]).buffer);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:private-media");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  });

  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it("revokes cached plaintext image and audio URLs on context switch", async () => {
    await fetchAndDecryptImage("", "private.webp", "key", "nonce");
    await fetchAndDecryptAudio("", "private.webm", "key", "nonce");
    invalidateWorkspaceCaches();
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it("rejects an image decrypt completed after context switch without caching it", async () => {
    let complete!: (data: ArrayBuffer) => void;
    mocks.decrypt.mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
    const pending = fetchAndDecryptImage("", "late.webp", "key", "nonce");
    await Promise.resolve();
    await Promise.resolve();
    invalidateWorkspaceCaches();
    complete(new Uint8Array([1]).buffer);
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=teams.cache.bounded-isolated
  it("rejects an audio decrypt completed after context switch without caching it", async () => {
    let complete!: (data: ArrayBuffer) => void;
    mocks.decrypt.mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
    const pending = fetchAndDecryptAudio("", "late.webm", "key", "nonce");
    await Promise.resolve();
    await Promise.resolve();
    invalidateWorkspaceCaches();
    complete(new Uint8Array([1]).buffer);
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
