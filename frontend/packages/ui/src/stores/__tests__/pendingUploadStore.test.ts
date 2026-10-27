// frontend/packages/ui/src/stores/__tests__/pendingUploadStore.test.ts
// Unit tests for pending upload message previews.
// Ensures deferred-send placeholders render the snapshotted editor content
// while the persisted message body is still empty waiting for upload completion.

import { afterEach, describe, expect, it } from "vitest";
import { get } from "svelte/store";
import {
  addPendingSend,
  buildPendingSendPreviewContent,
  claimPendingSendPrivacy,
  getReadyPendingSend,
  markPendingSendPrivacyFailure,
  pendingUploadStore,
  removePendingSend,
  type PendingSendContext,
} from "../pendingUploadStore";

describe("buildPendingSendPreviewContent", () => {
  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it("preserves a recording embed for a waiting deferred send", () => {
    const context: PendingSendContext = {
      pendingId: "message-1-pending",
      chatId: "chat-1",
      messageId: "message-1",
      editorSnapshot: {
        type: "doc",
        content: [
          {
            type: "paragraph",
            content: [
              { type: "text", text: "Listen to this" },
            ],
          },
          {
            type: "embed",
            attrs: {
              id: "recording-local-1",
              type: "recording",
              status: "transcribing",
              filename: "Voice note",
              blobUrl: "blob:http://localhost/recording",
            },
          },
        ],
      },
      embedSnapshots: new Map([
        [
          "recording-local-1",
          {
            embedId: "recording-local-1",
            embedType: "recording",
            filename: "Voice note",
            uploadEmbedId: null,
            contentRef: null,
          },
        ],
      ]),
      blockingEmbedIds: new Set(["recording-local-1"]),
      embedProgress: new Map([
        [
          "recording-local-1",
          {
            embedId: "recording-local-1",
            status: "transcribing",
            uploadPercent: 100,
            label: "Voice note",
          },
        ],
      ]),
      createdAt: 0,
      piiExclusions: new Set(),
      piiRewriteMappings: [],
      partialMarkdown: "",
    };

    const preview = buildPendingSendPreviewContent(context);
    const embedNode = preview?.content?.find((node) => node.type === "embed");

    expect(embedNode?.attrs?.type).toBe("recording");
    expect(embedNode?.attrs?.status).toBe("transcribing");
    expect(embedNode?.attrs?.filename).toBe("Voice note");
    expect(preview?.content?.[0]?.content?.[0]?.text).toBe("Listen to this");
  });
});


describe("deferred privacy scan recovery", () => {
  const contexts: PendingSendContext[] = [];
  const context = (id: string, blocked = false): PendingSendContext => ({
    pendingId: id, messageId: id, chatId: "privacy-recovery", editorSnapshot: { type: "doc", content: [] },
    embedSnapshots: new Map(), blockingEmbedIds: new Set(blocked ? ["upload"] : []),
    embedProgress: new Map(), createdAt: 0, piiExclusions: new Set(), piiRewriteMappings: [], partialMarkdown: "",
  });
  const add = (id: string, blocked = false) => {
    const ctx = context(id, blocked);
    contexts.push(ctx);
    addPendingSend(ctx);
    return ctx;
  };
  afterEach(() => { for (const ctx of contexts.splice(0)) removePendingSend(ctx.chatId, ctx.pendingId); });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it("retains a claimed context and blocks duplicate automatic claims", () => {
    const ctx = add("first");
    expect(getReadyPendingSend(ctx.chatId)).toBe(ctx);
    expect(claimPendingSendPrivacy(ctx)).toBe(true);
    expect(ctx.privacyScanState).toBe("scanning");
    expect(get(pendingUploadStore).get(ctx.chatId)?.[0]).toBe(ctx);
    expect(getReadyPendingSend(ctx.chatId)).toBeUndefined();
    expect(claimPendingSendPrivacy(ctx, true)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it("requires explicit retry after failure and preserves FIFO order", () => {
    const first = add("first");
    const second = add("second");
    expect(claimPendingSendPrivacy(first)).toBe(true);
    markPendingSendPrivacyFailure(first);
    expect(first.privacyScanState).toBe("failed");
    expect(getReadyPendingSend(first.chatId)).toBeUndefined();
    expect(claimPendingSendPrivacy(first)).toBe(false);
    expect(claimPendingSendPrivacy(second, true)).toBe(false);
    expect(claimPendingSendPrivacy(first, true)).toBe(true);
    removePendingSend(first.chatId, first.pendingId);
    expect(getReadyPendingSend(second.chatId)).toBe(second);
  });

  // contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
  it("does not claim incomplete uploads or resurrect a removed context", () => {
    const ctx = add("blocked", true);
    expect(claimPendingSendPrivacy(ctx, true)).toBe(false);
    ctx.blockingEmbedIds.clear();
    expect(claimPendingSendPrivacy(ctx)).toBe(true);
    removePendingSend(ctx.chatId, ctx.pendingId);
    markPendingSendPrivacyFailure(ctx);
    expect(get(pendingUploadStore).has(ctx.chatId)).toBe(false);
  });
});
