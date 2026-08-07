// @vitest-environment jsdom
// Defines targeted correction behavior for server-verified final Markdown.
// One changed block may be replaced without touching unrelated committed blocks.
// Broad non-local divergence must never request whole-message replacement.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { describe, expect, it, vi } from "vitest";
import type { Editor } from "@tiptap/core";
import { Schema } from "@tiptap/pm/model";
import { EditorState } from "@tiptap/pm/state";

vi.mock("../../data/modelsMetadata", () => ({ modelsMetadata: [] }));
vi.mock("../../data/matesMetadata", () => ({ matesMetadata: [] }));
vi.mock("../../data/providersMetadata", () => ({ providersMetadata: {} }));
vi.mock("../../stores/appSettingsMemoriesStore", () => ({
  appSettingsMemoriesStore: { subscribe: () => () => undefined },
}));
vi.mock("../../stores/appSkillsStore", () => ({
  appSkillsStore: { apps: {}, subscribe: () => () => undefined },
}));

import { createAssistantRenderPlan } from "../streamingMessageBlocks";
import { applyIncrementalUpdate } from "../streamingDocDiff";

const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: { content: "inline*", group: "block" },
    blockAtom: { group: "block", atom: true },
    text: { group: "inline" },
  },
});

function runRejectedDiff(oldContent: Record<string, unknown>, newContent: Record<string, unknown>) {
  const oldDoc = schema.nodeFromJSON(oldContent);
  const newDoc = schema.nodeFromJSON(newContent);
  const realState = EditorState.create({ doc: oldDoc });
  const rejectedTransaction = { maybeStep: vi.fn((_step: unknown) => ({ failed: "rejected" })) };
  const dispatched = vi.fn();
  let transactionReadCount = 0;
  const editor = {
    isDestroyed: false,
    state: {
      doc: oldDoc,
      schema,
      get tr() {
        transactionReadCount += 1;
        return transactionReadCount === 1 ? rejectedTransaction : realState.tr;
      },
    },
    view: { dispatch: dispatched },
  } as unknown as Editor;

  return {
    result: applyIncrementalUpdate(editor, newContent),
    rejectedTransaction,
    dispatched,
    transactionReadCount: () => transactionReadCount,
    newDoc,
  };
}

describe("assistant block corrections", () => {
  it("commits only the previous mutable tail on normal completion", () => {
    const streaming = createAssistantRenderPlan("One.\n\nTwo.", { phase: "streaming" });
    const completed = createAssistantRenderPlan("One.\n\nTwo.", {
      phase: "final",
      previous: streaming,
    });

    expect(completed.operations).toEqual([
      expect.objectContaining({ kind: "commit-tail" }),
    ]);
  });

  it("replaces only one locally corrected committed block", () => {
    const previous = createAssistantRenderPlan("One.\n\nBad quote.\n\nThree.", { phase: "final" });
    const corrected = createAssistantRenderPlan("One.\n\nVerified quote.\n\nThree.", {
      phase: "final",
      previous,
    });

    expect(corrected.operations).toEqual([
      expect.objectContaining({ kind: "replace-block", index: 1 }),
    ]);
    expect(corrected.committed[0].id).toBe(previous.committed[0].id);
    expect(corrected.committed[2].id).toBe(previous.committed[2].id);
  });

  it("targets each changed block without a full replacement operation", () => {
    const previous = createAssistantRenderPlan("One.\n\nTwo.\n\nThree.", { phase: "final" });
    const divergent = createAssistantRenderPlan("Changed one.\n\nTwo.\n\nChanged three.", {
      phase: "final",
      previous,
    });

    expect(divergent.operations).toEqual([
      expect.objectContaining({ kind: "replace-block", index: 0 }),
      expect.objectContaining({ kind: "replace-block", index: 2 }),
    ]);
    expect(divergent.operations.map((operation) => operation.kind) as string[]).not.toContain(
      "replace-document",
    );
  });

  it("retries a rejected inline-to-block diff as one targeted block replacement", () => {
    const harness = runRejectedDiff(
      {
        type: "doc",
        content: [
          { type: "paragraph", content: [{ type: "text", text: "stable" }] },
          { type: "paragraph", content: [{ type: "text", text: "provisional" }] },
        ],
      },
      {
        type: "doc",
        content: [
          { type: "paragraph", content: [{ type: "text", text: "stable" }] },
          { type: "blockAtom" },
        ],
      },
    );

    expect(harness.result).toEqual({ applied: true, fallback: true, stepsApplied: 1 });
    expect(harness.rejectedTransaction.maybeStep).toHaveBeenCalledTimes(1);
    expect(harness.transactionReadCount()).toBe(2);
    expect(harness.dispatched).toHaveBeenCalledTimes(1);
    expect(harness.dispatched.mock.calls[0][0].doc.eq(harness.newDoc)).toBe(true);
  });

  it("retries an inserted block without replacing shifted stable siblings", () => {
    const harness = runRejectedDiff(
      {
        type: "doc",
        content: [
          { type: "paragraph", content: [{ type: "text", text: "stable-a" }] },
          { type: "paragraph", content: [{ type: "text", text: "stable-b" }] },
        ],
      },
      {
        type: "doc",
        content: [
          { type: "paragraph", content: [{ type: "text", text: "stable-a" }] },
          { type: "blockAtom" },
          { type: "paragraph", content: [{ type: "text", text: "stable-b" }] },
        ],
      },
    );

    expect(harness.result).toEqual({
      applied: true,
      fallback: true,
      stepsApplied: 1,
    });
    expect(harness.transactionReadCount()).toBe(2);
    expect(harness.dispatched).toHaveBeenCalledOnce();
    expect(harness.dispatched.mock.calls[0][0].doc.eq(harness.newDoc)).toBe(true);
  });

  it("converges oversized documents with one bounded replacement transaction", () => {
    const paragraphs = Array.from({ length: 513 }, (_, index) => ({
      type: "paragraph",
      content: [{ type: "text", text: `paragraph-${index}` }],
    }));
    const harness = runRejectedDiff(
      { type: "doc", content: paragraphs },
      {
        type: "doc",
        content: [
          ...paragraphs.slice(0, -1),
          { type: "paragraph", content: [{ type: "text", text: "corrected-final-paragraph" }] },
        ],
      },
    );

    expect(harness.result).toEqual({ applied: true, fallback: true, stepsApplied: 1 });
    expect(harness.dispatched).toHaveBeenCalledOnce();
    expect(harness.dispatched.mock.calls[0][0].doc.eq(harness.newDoc)).toBe(true);
  });
});
