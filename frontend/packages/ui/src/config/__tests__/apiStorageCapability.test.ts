import { afterEach, describe, expect, it, vi } from "vitest";
import { getApiEndpoint, getWebSocketUrl, storageArchiveFetch } from "../api";

afterEach(() => vi.unstubAllGlobals());

describe("archive client capability", () => {
  // contract-test: supporting surface=gui.web assertions=storage.rollout.verified-24-hour-buffer
  it("advertises archive support on the authenticated WebSocket", () => {
    const url = new URL(getWebSocketUrl("session", "token"));
    expect(url.searchParams.get("client_capabilities")?.split(",")).toContain("agentic-storage-v2");
  });

  // contract-test: supporting surface=gui.web assertions=storage.rollout.verified-24-hour-buffer
  it("preserves request headers and credentials while declaring API support", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    await storageArchiveFetch(getApiEndpoint("/v1/chats/chat/messages/window"), {
      credentials: "include", headers: { "Content-Type": "application/json", "X-Request-Test": "kept" },
    });
    const init = fetchMock.mock.calls[0][1];
    expect(init.credentials).toBe("include");
    expect(init.headers.get("X-OpenMates-Client-Capabilities")).toBe("agentic-storage-v2");
    expect(init.headers.get("X-Request-Test")).toBe("kept");
  });

  // contract-test: supporting surface=gui.web assertions=storage.rollout.verified-24-hour-buffer
  it("leaves external object downloads unchanged", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("bytes"));
    vi.stubGlobal("fetch", fetchMock);
    const init = { headers: { "X-Test": "kept" } };
    await storageArchiveFetch("https://objects.example.invalid/archive", init);
    expect(fetchMock).toHaveBeenCalledWith("https://objects.example.invalid/archive", init);
  });
});
