// Regression for TASK-1610: a user message whose uploaded file followed the
// chat model's @ai-model mention on the same line rendered raw embed JSON and
// a broken code block instead of the image embed.
// Related: message_parsing/embedFenceRepair.ts, handlers/chatModelSendRouting.ts
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../services/chatSyncService", () => ({ chatSyncService: {} }));
import { parse_message } from "../parse_message";
import { findRawEmbedReferenceNodes, repairInlineEmbedFences, reportRawEmbedReferences, RAW_EMBED_RENDER_LOG_TAG } from "../embedFenceRepair";

const EMBED_ID = "ea6cc310-1c03-4250-a642-a4051d99d6d1";
const FENCE = `\`\`\`json\n{"type": "image", "embed_id": "${EMBED_ID}"}\n\`\`\``;
const BROKEN = `@ai-model:gemini-3.8-flash:google ${FENCE}\n\n Turn this into an embroidery patch for my 200 x 300 mm hoop`;

function collect(node: any, out: any[] = []): any[] {
  if (!node) return out;
  out.push(node);
  for (const child of node.content ?? []) collect(child, out);
  return out;
}

describe("user message with a model mention before an uploaded file", () => {
  afterEach(() => vi.restoreAllMocks());

  // contract-test: supporting surface=gui.web assertions=chats.rendering.embed-references-never-raw
  it("moves the embed fence onto its own block", () => {
    expect(repairInlineEmbedFences(BROKEN)).toBe(
      `@ai-model:gemini-3.8-flash:google\n\n${FENCE}\n\n Turn this into an embroidery patch for my 200 x 300 mm hoop`,
    );
    expect(repairInlineEmbedFences("plain ```json\n{\"a\": 1}\n```")).toBe("plain ```json\n{\"a\": 1}\n```");
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.embed-references-never-raw
  it("renders the stored broken message as an embed, not raw JSON", () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const doc = parse_message(BROKEN, "read", { unifiedParsingEnabled: true, role: "user" });
    const nodes = collect(doc);
    expect(nodes.some((node) => node.type === "codeBlock")).toBe(false);
    expect(nodes.some((node) => JSON.stringify(node.attrs ?? {}).includes(EMBED_ID))).toBe(true);
    expect(findRawEmbedReferenceNodes(doc)).toEqual([]);
    expect(errors.mock.calls.some((call) => String(call[0]).includes(RAW_EMBED_RENDER_LOG_TAG))).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=chats.rendering.embed-references-never-raw
  it("reports a document that still shows a raw embed reference, without content", () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const doc = { type: "doc", content: [{ type: "codeBlock", content: [{ type: "text", text: `{"type": "image", "embed_id": "${EMBED_ID}"}` }] }] };
    expect(reportRawEmbedReferences(doc, { role: "user", messageKey: "k1" })).toBe(true);
    expect(errors).toHaveBeenCalledTimes(1);
    expect(String(errors.mock.calls[0][0])).toContain(RAW_EMBED_RENDER_LOG_TAG);
    expect(JSON.stringify(errors.mock.calls[0])).not.toContain(EMBED_ID);
    reportRawEmbedReferences(doc, { role: "user", messageKey: "k1" });
    expect(errors).toHaveBeenCalledTimes(1);
  });
});
