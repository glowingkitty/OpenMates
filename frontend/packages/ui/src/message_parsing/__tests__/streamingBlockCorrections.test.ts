// @vitest-environment jsdom
// Defines targeted correction behavior for server-verified final Markdown.
// One changed block may be replaced without touching unrelated committed blocks.
// Broad non-local divergence must never request whole-message replacement.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

import { describe, expect, it, vi } from "vitest";
import type { Editor } from "@tiptap/core";
import { Slice } from "@tiptap/pm/model";

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
    const stableChild = { nodeSize: 5, eq: vi.fn(() => true) };
    const changedOldChild = { nodeSize: 5, eq: vi.fn(() => false) };
    const changedNewChild = { nodeSize: 5 };
    const oldDoc = {
      childCount: 2,
      content: {
        size: 10,
        findDiffStart: vi.fn(() => 6),
        findDiffEnd: vi.fn(() => ({ a: 7, b: 7 })),
      },
      child: vi.fn((index: number) => index === 0 ? stableChild : changedOldChild),
      eq: vi.fn(() => false),
    };
    const newDoc = {
      childCount: 2,
      content: { size: 10 },
      child: vi.fn((index: number) => index === 0 ? stableChild : changedNewChild),
      slice: vi.fn(() => Slice.empty),
    };
    const rejectedTransaction = { maybeStep: vi.fn((_step: unknown) => ({ failed: "incompatible open depths" })) };
    const fallbackTransaction = { maybeStep: vi.fn((_step: unknown) => ({ failed: null })) };
    let transactionReadCount = 0;
    const dispatch = vi.fn();
    const editor = {
      isDestroyed: false,
      state: {
        doc: oldDoc,
        schema: { nodeFromJSON: vi.fn(() => newDoc) },
        get tr() {
          transactionReadCount += 1;
          return transactionReadCount === 1 ? rejectedTransaction : fallbackTransaction;
        },
      },
      view: { dispatch },
    } as unknown as Editor;

    const result = applyIncrementalUpdate(editor, { type: "doc" });

    expect(result).toEqual({ applied: true, fallback: true, stepsApplied: 1 });
    expect(rejectedTransaction.maybeStep).toHaveBeenCalledTimes(1);
    expect(transactionReadCount).toBe(2);
    expect(fallbackTransaction.maybeStep).toHaveBeenCalledTimes(1);
    expect(fallbackTransaction.maybeStep.mock.calls[0][0]).toMatchObject({ from: 5, to: 10 });
    expect(dispatch).toHaveBeenCalledTimes(1);
    expect(dispatch).toHaveBeenCalledWith(fallbackTransaction);
  });

  it("does not index-align a rejected diff across inserted or removed blocks", () => {
    const oldDoc = {
      childCount: 1,
      content: {
        size: 5,
        findDiffStart: vi.fn(() => 1),
        findDiffEnd: vi.fn(() => ({ a: 2, b: 2 })),
      },
      eq: vi.fn(() => false),
    };
    const newDoc = {
      childCount: 2,
      content: { size: 10 },
      slice: vi.fn(() => Slice.empty),
    };
    const rejectedTransaction = { maybeStep: vi.fn((_step: unknown) => ({ failed: "rejected" })) };
    let transactionReadCount = 0;
    const dispatch = vi.fn();
    const editor = {
      isDestroyed: false,
      state: {
        doc: oldDoc,
        schema: { nodeFromJSON: vi.fn(() => newDoc) },
        get tr() {
          transactionReadCount += 1;
          return rejectedTransaction;
        },
      },
      view: { dispatch },
    } as unknown as Editor;

    expect(applyIncrementalUpdate(editor, { type: "doc" })).toEqual({
      applied: false,
      fallback: false,
      stepsApplied: 0,
    });
    expect(transactionReadCount).toBe(1);
    expect(dispatch).not.toHaveBeenCalled();
  });
});
