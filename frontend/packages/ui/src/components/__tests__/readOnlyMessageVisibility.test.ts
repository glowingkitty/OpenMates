// @vitest-environment jsdom
import { mount, tick, unmount } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

const { editorCreated } = vi.hoisted(() => ({ editorCreated: vi.fn() }));
vi.mock("@tiptap/core", () => ({
  Editor: class {
    view = { dom: document.createElement("div") };
    constructor(options: { element: HTMLElement; content: unknown }) {
      editorCreated(options.content);
      options.element.appendChild(this.view.dom);
    }
    destroy() {}
  },
}));
vi.mock("@tiptap/starter-kit", () => ({ default: { configure: () => ({ name: "starterKit" }) } }));
vi.mock("@repo/ui", async () => {
  const { readable } = await import("svelte/store");
  return { text: readable((key: string) => key) };
});
vi.mock("../enter_message/extensions/Embed", () => ({ Embed: { name: "embed" } }));
vi.mock("../enter_message/extensions/MateNode", () => ({ MateNode: { name: "mate" } }));
vi.mock("../enter_message/extensions/AIModelMentionNode", () => ({ AIModelMentionNode: { name: "model" } }));
vi.mock("../enter_message/extensions/GenericMentionNode", () => ({ GenericMentionNode: { name: "mention" } }));
vi.mock("../enter_message/extensions/BestModelMentionNode", () => ({ BestModelMentionNode: { name: "best" } }));
vi.mock("../enter_message/extensions/EmbedInlineNode", () => ({ EmbedInlineNode: { name: "inline" } }));
vi.mock("../enter_message/extensions/WikiInlineNode", () => ({ WikiInlineNode: { name: "wiki" } }));
vi.mock("../enter_message/extensions/SourceQuoteNode", () => ({ SourceQuoteNode: { name: "quote" } }));
vi.mock("../enter_message/extensions/EmbedPreviewLargeNode", () => ({ EmbedPreviewLargeNode: { name: "preview" } }));
vi.mock("../enter_message/extensions/InteractiveQuestionNode", () => ({ InteractiveQuestionNode: { configure: () => ({ name: "question" }) } }));
vi.mock("../enter_message/extensions/MarkdownExtensions", () => ({ MarkdownExtensions: [] }));
vi.mock("../enter_message/services/piiDetectionService", () => ({ getPIILabel: () => "Private" }));
vi.mock("../../stores/piiVisibilityStore", () => ({ piiVisibilityStore: { toggle: vi.fn() } }));
vi.mock("../../stores/settingsDeepLinkStore", () => ({ settingsDeepLink: {} }));
vi.mock("../../stores/panelStateStore", () => ({ panelState: {} }));
vi.mock("../../data/modelsMetadata", () => ({ modelsMetadata: [] }));
vi.mock("../../data/matesMetadata", () => ({ matesMetadata: [] }));
vi.mock("../../data/providersMetadata", () => ({ providersMetadata: {} }));
vi.mock("../../stores/appSettingsMemoriesStore", () => ({ appSettingsMemoriesStore: { subscribe: () => () => undefined } }));
vi.mock("../../stores/appSkillsStore", () => ({ appSkillsStore: { apps: {}, subscribe: () => () => undefined } }));

import ReadOnlyMessage from "../ReadOnlyMessage.svelte";

afterEach(() => {
  vi.unstubAllGlobals();
  editorCreated.mockClear();
  document.body.replaceChildren();
});

describe("message body visibility", () => {
  // contract-test: direct surface=gui.web assertions=hosting-domains.embeds.parent-child,hosting-domains.surface-parity
  it("initializes a visible message whose preceding provenance card pushes its body below the scrollport", async () => {
    const message = document.createElement("article");
    message.className = "chat-message";
    const provenance = document.createElement("div");
    provenance.textContent = "Workflow run";
    const body = document.createElement("div");
    message.append(provenance, body);
    document.body.append(message);
    let notifyVisibility: () => void = () => {};
    const disconnect = vi.fn();
    vi.stubGlobal("IntersectionObserver", class {
      constructor(private callback: IntersectionObserverCallback) {}
      observe(target: Element) {
        // Only the provenance is within the scrollport. An observer watching
        // just the editor cannot see it, even with an expanded viewport margin.
        notifyVisibility = () => this.callback([
          { isIntersecting: target.contains(provenance) } as IntersectionObserverEntry,
        ], this as unknown as IntersectionObserver);
      }
      disconnect = disconnect;
    });
    const content = { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "Checked domains:" }] }] };
    const component = mount(ReadOnlyMessage, { target: body, props: { content, role: "assistant" } });
    try {
      await tick();
      expect(editorCreated).not.toHaveBeenCalled();
      notifyVisibility();
      await tick();
      expect(editorCreated).toHaveBeenCalledExactlyOnceWith(content);
      notifyVisibility();
      expect(editorCreated).toHaveBeenCalledTimes(1);
    } finally {
      await unmount(component);
    }
    expect(disconnect).toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it("keeps offscreen messages lazy and supports standalone read-only bodies", async () => {
    const body = document.createElement("div");
    document.body.append(body);
    let reportVisibility: (visible: boolean) => void = () => {};
    vi.stubGlobal("IntersectionObserver", class {
      constructor(private callback: IntersectionObserverCallback) {}
      observe() {
        reportVisibility = (visible) => this.callback([
          { isIntersecting: visible } as IntersectionObserverEntry,
        ], this as unknown as IntersectionObserver);
      }
      disconnect() {}
    });
    const component = mount(ReadOnlyMessage, { target: body, props: { content: "Saved message" } });
    try {
      await tick();
      reportVisibility(false);
      await tick();
      expect(editorCreated).not.toHaveBeenCalled();
      reportVisibility(true);
      await tick();
      expect(editorCreated).toHaveBeenCalledTimes(1);
    } finally {
      await unmount(component);
    }
  });
});
