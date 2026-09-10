// @vitest-environment jsdom
// Component regression tests for UUID-backed embed reference hydration.
// Streaming can deliver the assistant reference before its embed payload.
// The preview must retry when the matching embedUpdated event arrives.
// All data is local and provider-free.

import { mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EmbedReferencePreview from "../EmbedReferencePreview.svelte";
import { embedRefIndexVersion, embedStore } from "../../../services/embedStore";

const embedResolverMocks = vi.hoisted(() => ({
  resolveEmbed: vi.fn(),
  decodeToonContent: vi.fn(),
}));

const rendererMocks = vi.hoisted(() => ({
  render: vi.fn(),
}));

const chatSyncMocks = vi.hoisted(() => {
  const listeners = new Map<string, Set<(event: Event) => void>>();
  return {
    listeners,
    service: {
      addEventListener: vi.fn((type: string, listener: (event: Event) => void) => {
        const registered = listeners.get(type) ?? new Set<(event: Event) => void>();
        registered.add(listener);
        listeners.set(type, registered);
      }),
      removeEventListener: vi.fn((type: string, listener: (event: Event) => void) => {
        listeners.get(type)?.delete(listener);
      }),
      dispatchEvent: vi.fn((event: Event) => {
        listeners.get(event.type)?.forEach((listener) => listener(event));
      }),
    },
  };
});

vi.mock("../../../services/embedResolver", () => embedResolverMocks);
vi.mock("../../../services/embedStore", async () => ({
  embedStore: {
    resolveByRef: vi.fn(() => null),
    resolveByRefDeep: vi.fn(async () => null),
  },
  embedRefIndexVersion: (await import("svelte/store")).writable(0),
}));
vi.mock("../../../services/chatSyncService", () => ({
  chatSyncService: chatSyncMocks.service,
}));
vi.mock("../../enter_message/extensions/embed_renderers", () => ({
  getEmbedRenderer: vi.fn(() => ({ render: rendererMocks.render })),
}));

async function flush(): Promise<void> {
  for (let index = 0; index < 5; index += 1) await Promise.resolve();
  await tick();
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

describe("EmbedReferencePreview", () => {
  beforeEach(() => {
    embedResolverMocks.resolveEmbed.mockReset();
    embedResolverMocks.decodeToonContent.mockReset();
    rendererMocks.render.mockReset();
    chatSyncMocks.listeners.clear();
    vi.mocked(embedStore.resolveByRef).mockReturnValue(null);
    embedRefIndexVersion.set(0);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("ends unresolved reference loading after bounded retries", async () => {
    const target = document.createElement("div");
    document.body.appendChild(target);
    const component = mount(EmbedReferencePreview, {
      target,
      props: { embedRef: "missing-event-A1b" },
    });
    try {
      await flush();
      expect(target.textContent).toContain("Loading preview...");
      await vi.advanceTimersByTimeAsync(7_000);
      await flush();
      expect(target.textContent).toContain("Preview unavailable");
      expect(target.textContent).not.toContain("Loading preview...");
    } finally {
      await unmount(component);
      target.remove();
    }
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("renders an event when its reference arrives after mount", async () => {
    const embedId = "delayed-event-id";
    embedResolverMocks.resolveEmbed.mockResolvedValue({
      embed_id: embedId, type: "event", status: "finished", content: "event-content",
    });
    embedResolverMocks.decodeToonContent.mockResolvedValue({
      type: "event_result", app_id: "events", skill_id: "search", title: "Community workshop",
    });
    const target = document.createElement("div");
    document.body.appendChild(target);
    const component = mount(EmbedReferencePreview, {
      target, props: { embedRef: "community-workshop-A1b" },
    });
    try {
      await flush();
      expect(target.textContent).toContain("Loading preview...");
      vi.mocked(embedStore.resolveByRef).mockReturnValue(embedId);
      embedRefIndexVersion.update((version) => version + 1);
      await flush();
      expect(rendererMocks.render).toHaveBeenCalledWith(expect.objectContaining({
        attrs: expect.objectContaining({ type: "events-event", title: "Community workshop" }),
      }));
      expect(target.textContent).not.toContain("Loading preview...");
      await vi.advanceTimersByTimeAsync(7_000);
      expect(target.textContent).not.toContain("Preview unavailable");
    } finally {
      await unmount(component);
      target.remove();
    }
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("hydrates when embed data arrives after the streamed reference", async () => {
    const embedId = "application-embed-id";
    embedResolverMocks.resolveEmbed
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValue({
        embed_id: embedId,
        type: "application",
        status: "finished",
        content: "application-content",
        app_id: "code",
        skill_id: "application",
      });
    embedResolverMocks.decodeToonContent.mockResolvedValue({
      type: "application",
      app_id: "code",
      skill_id: "application",
      name: "Generated application",
      file_refs: [],
    });

    const target = document.createElement("div");
    document.body.appendChild(target);
    const component = mount(EmbedReferencePreview, {
      target,
      props: {
        embedRef: embedId,
        embedId,
      },
    });

    await flush();
    expect(rendererMocks.render).not.toHaveBeenCalled();
    expect(target.textContent).toContain("Loading preview...");

    chatSyncMocks.service.dispatchEvent(new CustomEvent("embedUpdated", {
      detail: { embed_id: embedId, status: "finished" },
    }));
    await flush();
    expect(rendererMocks.render).not.toHaveBeenCalled();

    // The update retries immediately after the initial miss. Its next miss
    // uses the second (2-second) bounded backoff interval.
    await vi.advanceTimersByTimeAsync(2_000);
    await flush();

    expect(embedResolverMocks.resolveEmbed).toHaveBeenCalledTimes(3);
    expect(rendererMocks.render).toHaveBeenCalledWith(expect.objectContaining({
      attrs: expect.objectContaining({
        id: embedId,
        type: "code-application",
        status: "finished",
        app_id: "code",
        skill_id: "application",
      }),
    }));

    unmount(component);
    target.remove();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("does not render stale data after a terminal embed update", async () => {
    const embedId = "failed-application-embed-id";
    const pendingEmbed = deferred<Record<string, unknown> | null>();
    embedResolverMocks.resolveEmbed.mockReturnValue(pendingEmbed.promise);
    embedResolverMocks.decodeToonContent.mockResolvedValue({ type: "application" });

    const target = document.createElement("div");
    document.body.appendChild(target);
    const component = mount(EmbedReferencePreview, {
      target,
      props: { embedRef: embedId, embedId },
    });
    await flush();

    chatSyncMocks.service.dispatchEvent(new CustomEvent("embedUpdated", {
      detail: { embed_id: embedId, status: "error" },
    }));
    pendingEmbed.resolve({
      embed_id: embedId,
      type: "application",
      status: "finished",
      content: "stale-application-content",
    });
    await flush();

    expect(rendererMocks.render).not.toHaveBeenCalled();
    expect(target.textContent).toContain("Preview unavailable");

    unmount(component);
    target.remove();
  });
});
