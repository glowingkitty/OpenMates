import { afterEach, describe, expect, it, vi } from "vitest";
import { getProfileImageBlobUrl, invalidateProfileImageCache } from "../profileImageService";

const users = new Set<string>();

function imageResponse(): Response {
  return new Response(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), { headers: { "Content-Type": "image/jpeg" } });
}

afterEach(() => {
  for (const user of users) invalidateProfileImageCache(user);
  users.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("profileImageService", () => {
  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it("loads an existing private image when the session omits its URL", async () => {
    const userId = "user-with-image";
    users.add(userId);
    const fetchMock = vi.fn().mockResolvedValue(imageResponse());
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:profile-image"),
      revokeObjectURL: vi.fn(),
    });

    await expect(getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId))
      .resolves.toBe("blob:profile-image");
    expect(fetchMock).toHaveBeenCalledWith(
      `https://api.dev.openmates.org/v1/users/${userId}/profile-image`,
      { credentials: "include" },
    );
    await expect(getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId))
      .resolves.toBe("blob:profile-image");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible
  it("uses the placeholder when no image exists", async () => {
    const userId = "user-without-image";
    users.add(userId);
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId))
      .resolves.toBeNull();
    await expect(getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId))
      .resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(30_000);
    await getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    invalidateProfileImageCache(userId);
    await getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it.each([401, 503])("retries transient HTTP %s failures without caching absence", async (status) => {
    const userId = `user-retry-${status}`;
    users.add(userId);
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status }));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "error").mockImplementation(() => {});
    await getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId);
    await getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it("retries network failures without caching absence", async () => {
    const userId = "user-network-retry";
    users.add(userId);
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Network unavailable"));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "error").mockImplementation(() => {});
    await getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId);
    await getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it("does not share absence between accounts or changed image endpoints", async () => {
    users.add("missing-a"); users.add("missing-b");
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);
    await getProfileImageBlobUrl(null, "https://api.dev.openmates.org", "missing-a");
    await getProfileImageBlobUrl(null, "https://api.dev.openmates.org", "missing-b");
    await getProfileImageBlobUrl("/v1/new-image", "https://api.dev.openmates.org", "missing-a");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it("does not let a stale 404 suppress requests after upload invalidation", async () => {
    const userId = "user-stale-missing";
    users.add(userId);
    let resolveOld!: (response: Response) => void;
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise<Response>(resolve => { resolveOld = resolve; }))
      .mockResolvedValue(new Response(null, { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const old = getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId);
    await Promise.resolve();
    invalidateProfileImageCache(userId);
    resolveOld(new Response(null, { status: 404 }));
    await old;
    await getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it("does not let a request from before invalidation overwrite a new upload", async () => {
    const userId = "user-reuploading";
    users.add(userId);
    let resolveOld!: (response: Response) => void;
    const oldResponse = new Promise<Response>((resolve) => { resolveOld = resolve; });
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => oldResponse)
      .mockResolvedValueOnce(imageResponse());
    const createObjectURL = vi.fn(() => "blob:new-image");
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL: vi.fn() });

    const oldRequest = getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId);
    await Promise.resolve();
    invalidateProfileImageCache(userId);
    const newRequest = getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId);
    await expect(newRequest).resolves.toBe("blob:new-image");
    resolveOld(imageResponse());
    await expect(oldRequest).resolves.toBeNull();
    await expect(getProfileImageBlobUrl(null, "https://api.dev.openmates.org", userId))
      .resolves.toBe("blob:new-image");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(createObjectURL).toHaveBeenCalledOnce();
  });
});
