// frontend/packages/ui/src/stores/__tests__/pendingUploadStore.test.ts
// Unit tests for pending upload message previews.
// Ensures deferred-send placeholders render the snapshotted editor content
// while the persisted message body is still empty waiting for upload completion.

import { describe, expect, it } from "vitest";
import {
  buildPendingSendPreviewContent,
  type PendingSendContext,
} from "../pendingUploadStore";

describe("buildPendingSendPreviewContent", () => {
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
