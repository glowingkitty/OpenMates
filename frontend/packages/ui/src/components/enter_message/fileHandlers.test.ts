/**
 * Regression coverage for message-input file attachment routing.
 *
 * Anonymous users may draft with local-only file previews before signup, but
 * the client must not upload file bytes or skip supported file types. These
 * tests keep that behavior in the file routing layer, below the Svelte UI.
 */
import { describe, expect, it, vi } from "vitest";
import { processFiles } from "./fileHandlers";

type InsertedEmbed = {
  type: "embed";
  attrs: Record<string, unknown>;
};

function createEditorStub() {
  const inserted: unknown[] = [];
  const chain = {
    focus: vi.fn(() => chain),
    insertContent: vi.fn((content: unknown) => {
      inserted.push(content);
      return chain;
    }),
    run: vi.fn(() => true),
  };

  return {
    inserted,
    isEmpty: false,
    state: {
      doc: {
        firstChild: {},
        descendants: vi.fn(),
      },
    },
    commands: {
      focus: vi.fn(),
      insertContentAt: vi.fn(),
      insertContent: vi.fn((content: unknown) => {
        inserted.push(content);
        return true;
      }),
    },
    chain: vi.fn(() => chain),
  };
}

function flattenInsertedEmbeds(inserted: unknown[]): InsertedEmbed[] {
  return inserted
    .flatMap((content) => (Array.isArray(content) ? content : [content]))
    .filter((content): content is InsertedEmbed => {
      return !!content && typeof content === "object" && (content as { type?: unknown }).type === "embed";
    });
}

describe("processFiles", () => {
  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("inserts a local PDF placeholder for anonymous uploads", async () => {
    const editor = createEditorStub();
    const file = new File([
      "%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF",
    ], "anonymous-upload.pdf", { type: "application/pdf" });

    await processFiles([file], editor as unknown as Parameters<typeof processFiles>[1], false);

    const [embed] = flattenInsertedEmbeds(editor.inserted);
    expect(embed?.attrs).toMatchObject({
      type: "pdf",
      status: "finished",
      filename: "anonymous-upload.pdf",
      contentRef: null,
      needsSignup: true,
      uploadEmbedId: null,
    });
  });

  // contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
  it("skips anonymous mind map uploads because they need authenticated embed storage", async () => {
    const editor = createEditorStub();
    const file = new File([
      JSON.stringify({ version: 1, title: "Private plan", nodes: [] }),
    ], "private-plan.ommindmap", { type: "application/json" });

    await processFiles([file], editor as unknown as Parameters<typeof processFiles>[1], false);

    expect(flattenInsertedEmbeds(editor.inserted)).toHaveLength(0);
    expect(editor.commands.focus).not.toHaveBeenCalled();
  });
});
