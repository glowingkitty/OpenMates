import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authStore } from "../../stores/authStore";

import { activeChatStore } from "../../stores/activeChatStore";
import {
  prepareIssueReportContextUrl,
  generateCurrentContextUrl,
  canShareIssueReportContext,
  submitIssueReport,
} from "../issueReportSubmission";

vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: {
    getKeySync: vi.fn(() => new Uint8Array([1, 2, 3])),
    getKey: vi.fn(),
  },
}));

vi.mock("../embedStore", () => ({
  embedStore: {},
}));

vi.mock("../../demo_chats/convertToChat", () => ({
  isPublicChat: vi.fn(() => false),
}));

vi.mock("../../stores/authStore", async () => {
  const { writable } = await import('svelte/store');
  return { authStore: writable({ isAuthenticated: true }) };
});

vi.mock("../db", () => ({
  chatDB: { getChat: vi.fn(async () => null) },
}));

vi.mock("../shareEncryption", () => ({
  generateShareKeyBlob: vi.fn(async () => "private-fragment"),
}));

describe("prepareIssueReportContextUrl", () => {
  beforeEach(() => authStore.update((state) => ({ ...state, isAuthenticated: true })));
  afterEach(() => {
    activeChatStore.setWithoutHashUpdate(null);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  // contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content
  it('omits anonymous chat links and never publishes their metadata', async () => {
    authStore.update((state) => ({ ...state, isAuthenticated: false }));
    activeChatStore.setWithoutHashUpdate('anonymous-local-chat');
    vi.stubGlobal('fetch', vi.fn());
    await expect(canShareIssueReportContext(
      `${window.location.origin}/share/chat/anonymous-local-chat#key=private-fragment`,
    )).resolves.toBe(false);
    await expect(generateCurrentContextUrl()).resolves.toBeNull();
    await expect(prepareIssueReportContextUrl(
      `${window.location.origin}/share/chat/anonymous-local-chat#key=private-fragment`,
    )).resolves.toBeNull();
    expect(globalThis.fetch).not.toHaveBeenCalled();

    // Signing in must not make an unpromoted tab-local record shareable.
    authStore.update((state) => ({ ...state, isAuthenticated: true }));
    await expect(generateCurrentContextUrl()).resolves.toBeNull();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=issue-reporting.submission.confirmed-and-durable
  it("continues without a context URL when sharing fails", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Chat not found" }),
    })));

    const result = await prepareIssueReportContextUrl(
      `${window.location.origin}/share/chat/new-chat#key=private-fragment`,
    );

    expect(result).toBeNull();
    expect(globalThis.fetch).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("Continuing without shared context"),
    );
    expect(warn.mock.calls.flat().join(" ")).not.toContain("private-fragment");
  });

  // contract-test: supporting surface=gui.web assertions=chat-share-settings.shared-link-open
  it("keeps an embed context URL after metadata sharing succeeds", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({ success: true }),
    })));
    const shareUrl = `${window.location.origin}/share/embed/embed-1#key=private-fragment`;

    await expect(prepareIssueReportContextUrl(shareUrl)).resolves.toBe(shareUrl);
  });

  // contract-test: supporting surface=gui.web assertions=issue-reporting.submission.confirmed-and-durable
  it("posts the report without chat plaintext or its unusable share URL after a 404", async () => {
    activeChatStore.setWithoutHashUpdate("new-private-chat");
    vi.spyOn(document, "querySelectorAll").mockReturnValue([] as unknown as NodeListOf<Element>);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/v1/share/chat/metadata")) {
        return new Response(JSON.stringify({ detail: "Chat not found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/v1/settings/issues")) {
        return new Response(JSON.stringify({
          success: true,
          issue_id: "issue-1",
          short_issue_id: "ABCDE",
        }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(submitIssueReport({
      title: "New chat failed",
      description: "Diagnostics should still be submitted",
      shareCurrentChat: true,
    })).resolves.toEqual({
      success: true,
      issueId: "issue-1",
      shortIssueId: "ABCDE",
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const metadataRequest = fetchMock.mock.calls[0];
    expect(String(metadataRequest[0])).toContain("/v1/share/chat/metadata");
    expect(JSON.stringify(metadataRequest[1])).not.toContain("private-fragment");

    const reportRequest = fetchMock.mock.calls[1];
    expect(String(reportRequest[0])).toContain("/v1/settings/issues");
    const payload = JSON.parse(String(reportRequest[1]?.body));
    expect(payload.chat_or_embed_url).toBeNull();
    expect(payload.last_messages_html).toBeNull();
    expect(payload.description).toBe("Diagnostics should still be submitted");
    expect(payload.device_info).toEqual(expect.objectContaining({
      userAgent: expect.any(String),
      viewportWidth: expect.any(Number),
      viewportHeight: expect.any(Number),
    }));
    expect(payload.runtime_debug_state).toEqual(expect.objectContaining({
      websocket_status: expect.anything(),
      is_online: expect.anything(),
      phased_sync_state: expect.any(Object),
    }));
    expect(String(reportRequest[1]?.body)).not.toContain("private-fragment");
    expect(String(fetchMock.mock.calls[2][0])).toContain('/v1/settings/issue-logs');
    expect(String(fetchMock.mock.calls[2][1]?.body)).not.toContain('private-fragment');
    expect(warn.mock.calls.flat().join(" ")).not.toContain("private-fragment");
  });
});
