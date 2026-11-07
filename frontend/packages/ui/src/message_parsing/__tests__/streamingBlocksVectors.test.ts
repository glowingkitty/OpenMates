// @vitest-environment jsdom
// TS-generated parity vectors for the shared Rust render-plan block model.
// The committed JSON (packages/openmates-rust/src/web_parse/blocks_ts_vectors.json) holds
// inputs plus outcomes of the TypeScript functions in streamingMessageBlocks.ts
// (flag off). This test fails when TypeScript drifts from the vectors and prints
// the regenerated file as VECTORS_B64 chunks (isolated CI has no local run);
// the Rust tests (web_parse/blocks_tests.rs) replay the same file.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../data/modelsMetadata", () => ({ modelsMetadata: [] }));
vi.mock("../../data/matesMetadata", () => ({ matesMetadata: [] }));
vi.mock("../../data/providersMetadata", () => ({ providersMetadata: {} }));
vi.mock("../../stores/appSettingsMemoriesStore", () => ({
  appSettingsMemoriesStore: { subscribe: () => () => undefined },
}));
vi.mock("../../stores/appSkillsStore", () => ({
  appSkillsStore: { apps: {}, subscribe: () => () => undefined },
}));

import {
  createAssistantRenderPlan,
  normalizeAssistantRenderPlan,
  type AssistantRenderPlan,
  type AssistantRenderPhase,
} from "../streamingMessageBlocks";

const VECTORS = resolve(__dirname, "../../../../../../packages/openmates-rust/src/web_parse/blocks_ts_vectors.json");

interface PreviousSummary {
  phase: AssistantRenderPhase;
  committed: Array<{ id: string; markdown: string }>;
  tail: { id: string; markdown: string } | null;
}

function summarize(plan: AssistantRenderPlan): PreviousSummary {
  return {
    phase: plan.phase,
    committed: plan.committed.map((b) => ({ id: b.id, markdown: b.markdown })),
    tail: plan.tail ? { id: plan.tail.id, markdown: plan.tail.markdown } : null,
  };
}

const HASH_INPUTS = ["", "a", "abc", "Hello, world", "café", "\u{1F600} emoji", "中文", "line\nbreak", "x".repeat(300)];

const FENCE = "```";
const SINGLE_RAW: Array<[string, AssistantRenderPhase] | string> = [
  ["", "streaming"], ["", "final"], ["   \n\n  ", "final"],
  ["Hello", "streaming"], ["Hello", "final"],
  ["One.\n\nTwo.", "streaming"], ["One.\n\nTwo.", "final"], ["One.\n\nTwo.\n\n", "streaming"],
  ["One.\r\n\r\nTwo.", "streaming"], ["One.\n\n\n\nTwo.\n\nThree", "streaming"],
  [" One. \n\n﻿Two. \n\nTail", "streaming"], ["A\u0085B\n\nC", "streaming"],
  ["Use [the event](embed:event-ref).\n\n[!](embed:preview-ref)\n\nStill writing the final paragraph", "streaming"],
  ["[!](embed:one)\n\n[!](embed:two)\n\nTail", "streaming"], ["[!](embed:one)\n\n[!](embed:two)", "final"],
  ["[!](embed:)\n\nx\n\ny", "streaming"], ["  [!](embed:a)  \n\n  [!](embed:b)  \n\nz", "streaming"],
  ["An [unfinished link](embed:", "streaming"], ["An [unfinished\n\nlink](embed:", "streaming"],
  ["Escaped \\[ bracket\n\nNext\n\nTail", "streaming"], ["Paren (open\n\nNext", "streaming"],
  ["Paren (open) closed\n\nNext\n\nTail", "streaming"], ["[a](b\n\nrest", "final"],
  [`${FENCE}json\n{"type":"app_skill_use"`, "streaming"], [`${FENCE}js\ncode\n\nmore\n${FENCE}\n\nafter`, "streaming"],
  [`${FENCE}js\ncode\n${FENCE}`, "streaming"], [`${FENCE}js\ncode\n${FENCE}\n\nTail`, "streaming"],
  [`text ${FENCE} inline fence\n\nTail`, "streaming"], ["````\n\nx\n\ny", "streaming"],
  ["- first item\n- second item", "streaming"], ["- first item\n\n  continued item text", "streaming"],
  ["1. one\n2. two\n\nTail", "streaming"], ["10. ten\n\nTail", "streaming"], ["* star\n\nTail", "streaming"],
  ["+ plus\n\nTail", "streaming"], ["-no space\n\nTail", "streaming"], ["1.no space\n\nTail", "streaming"],
  ["| A | B |\n|---|---|\n| 1 |", "streaming"], ["| A | B |\n|---|---|\n| 1 | 2 |\n\nTail", "streaming"],
  ["a | b\n---\n\nTail", "streaming"], ["a | b\n:---:\n\nTail", "streaming"], ["a | b\n|:----|\n\nTail", "streaming"],
  ["a | b\n--\n\nTail", "streaming"], ["pipe | only\n\nTail", "streaming"], ["a|b\r\n---\r\n\nTail", "streaming"],
  ["> an unfinished source quote", "streaming"], ["> [Source](embed:ref-1)\n\nTail", "streaming"],
  ["> [Source](embed:ref-1)  \n\nTail", "streaming"], ">   [Source](embed:ref-1)\n\nTail",
  ["> [](embed:ref-1)\n\nTail", "streaming"], ["> [Source](embed:)\n\nTail", "streaming"],
  ["> [Source](embed:ref) trailing\n\nTail", "streaming"], ["> quote\n\n> quote two\n\nTail", "streaming"],
  [" > indented quote\n\nTail", "streaming"], ["Heading\n### Weekend 1\n" + `${FENCE}embeds_results_view\nembeds: a, b\n${FENCE}` + "\n\nMore", "streaming"],
  ["Same.\n\nSame.\n\nSame.\n\nTail", "streaming"], ["Same.\n\nSame.", "final"],
  ["café \u{1F600}\n\n中文\n\nTail \u{1F600}", "streaming"],
];
const SINGLE: Array<[string, AssistantRenderPhase]> = SINGLE_RAW.map((c) => (typeof c === "string" ? [c, "streaming"] : c));

const SEQUENCES: Array<Array<[string, AssistantRenderPhase]>> = [
  [["First paragraph.\n\nStill", "streaming"], ["First paragraph.\n\nStill writing", "streaming"], ["First paragraph.\n\nStill writing.\n\nNext", "streaming"],
    ["First paragraph.\n\nStill writing.\n\nNext", "final"]],
  [["One.\n\nTwo.", "streaming"], ["One.\n\nTwo.", "final"]],
  [["One.\n\nBad quote.\n\nThree.", "final"], ["One.\n\nVerified quote.\n\nThree.", "final"]],
  [["One.\n\nTwo.\n\nThree.", "final"], ["Changed one.\n\nTwo.\n\nChanged three.", "final"]],
  [["One.\n\nTwo.\n\nThree.", "final"], ["One.\n\nThree.", "final"]],
  [["One.\n\nTwo.\n\nThree.", "final"], ["One.\n\nTwo.", "final"]],
  [["One.\n\nTwo.\n\nThree.", "final"], ["Zero.\n\nThree.", "final"]],
  [["One.\n\nTwo.\n\nThree.", "final"], ["X.", "final"]],
  [["One.\n\nTwo.", "final"], ["One.\n\nTwo.\n\nThree.", "final"]],
  [["Same.\n\nSame.", "final"], ["Same.\n\nSame.\n\nSame.", "final"], ["Same.", "final"]],
  [["One.\n\nTwo.", "final"], ["One.\n\nTwo.\n\nPartial", "streaming"], ["Different start", "streaming"]],
  [["Intro\n\nPartial", "streaming"], ["Intro\n\nPartial text.\n\nMore\n\nTail", "streaming"]],
  [["Here are the results.\n\n", "streaming"],
    ["Here are the results.\n\n### Weekend 1\n" + `${FENCE}embeds_results_view\ntitle: First weekend\nembeds: event-one, event-two\n${FENCE}\n\n`, "streaming"],
    ["Here are the results.\n\n### Weekend 1\n" + `${FENCE}embeds_results_view\ntitle: First weekend\nembeds: event-one, event-two\n${FENCE}\n\n### Weekend 2\n${FENCE}embeds_results_view\nembeds: event-three\n${FENCE}\n\nMore details follow.`, "streaming"]],
  [["A.\n\nB.", "streaming"], ["A.\n\nB.\n\nC.\n\nD.", "final"]],
];

function planSteps(steps: Array<[string, AssistantRenderPhase]>) {
  const cases: Array<Record<string, unknown>> = [];
  let previous: AssistantRenderPlan | undefined;
  for (const [markdown, phase] of steps) {
    const summary = previous ? summarize(previous) : null;
    const plan = createAssistantRenderPlan(markdown, { phase, previous });
    // The TS failure path returns the previous blocks with the failure operations.
    const failed = Boolean(previous) && plan.operations[0]?.kind === "convergence-failure";
    const reusedFrom = (block: unknown) => {
      const index = (previous?.committed ?? []).findIndex((candidate) => candidate === block);
      return index < 0 ? null : index;
    };
    const streamingReset = previous?.phase === "final" && phase === "streaming";
    cases.push({
      markdown,
      phase,
      previous: summary,
      out: failed
        ? { failed: true, operations: plan.operations }
        : {
            failed: false,
            committed: plan.committed.map((b) => ({ id: b.id, markdown: b.markdown, reuse: streamingReset ? null : reusedFrom(b) })),
            tail: plan.tail ? plan.tail.markdown : null,
            operations: plan.operations,
          },
    });
    previous = plan;
  }
  return cases;
}

function typedNode(type: string, extra: Record<string, unknown> = {}) {
  return { type, ...extra };
}

const NORMALIZE_PLANS = (() => {
  const embed = (attrs: Record<string, unknown>) => typedNode("embed", { attrs });
  const doc = (content: unknown[]) => ({ type: "doc", content });
  const paragraph = (content: unknown[] = []) => typedNode("paragraph", { content });
  const text = (value: string) => typedNode("text", { text: value });
  const documents = [
    doc([paragraph([text("hi")])]),
    doc([paragraph([text("a")]), embed({ type: "app-skill-use", id: "skill-1" }), embed({ type: "app-skill-use", id: 5 }), embed({ type: "app-skill-use" })]),
    doc([embed({ type: "app-skill-use-group", groupedItems: [{ id: "g1" }, { id: 2 }, {}, { id: "g3" }] }), embed({ type: "app-skill-use-group", groupedItems: "nope" })]),
    doc([typedNode("blockquote", { content: [paragraph([embed({ type: "app-skill-use", id: "nested" })])] }), typedNode("notEmbed", { attrs: { type: "app-skill-use", id: "ignored" } })]),
    doc([embed({ type: "embeds-map-view", id: "x" }), { content: [typedNode("noTypeParent")] }, typedNode("emptyContent", { content: [] }), typedNode("nonArrayContent", { content: "str" })]),
  ];
  return documents.map((document, index) => ({
    document,
    committed: documents.slice(0, index).map((d, i) => ({ markdown: `block ${i} é`, document: d })),
    tail: index % 2 === 0 ? { markdown: `tail ${index}`, document: documents[index] } : null,
  }));
})();

function buildVectors() {
  const plan: Array<Record<string, unknown>> = [];
  for (const single of SINGLE) plan.push(...planSteps([single]));
  for (const sequence of SEQUENCES) plan.push(...planSteps(sequence));
  const normalize = NORMALIZE_PLANS.map((input) => ({
    plan: input,
    out: normalizeAssistantRenderPlan(input as unknown as AssistantRenderPlan),
  }));
  const hash = HASH_INPUTS.map((value) => ({
    in: value,
    out: normalizeAssistantRenderPlan({
      committed: [{ markdown: value, document: {} }], tail: null, document: {},
    } as unknown as AssistantRenderPlan).blocks[0].id.replace("semantic:", ""),
  }));
  return { hash, plan, normalize };
}

describe("render plan block model vectors (TypeScript side)", () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it("committed vectors equal the TypeScript block model", () => {
    const generated = `${JSON.stringify(buildVectors(), null, 1)}\n`;
    let committed = "";
    try {
      committed = readFileSync(VECTORS, "utf8");
    } catch {
      committed = "";
    }
    if (committed !== generated) {
      const encoded = Buffer.from(generated, "utf8").toString("base64");
      const chunks = encoded.match(/.{1,2000}/g) ?? [];
      chunks.forEach((chunk, index) => console.log(`VECTORS_B64[${index + 1}/${chunks.length}] ${chunk}`));
    }
    expect(committed).toBe(generated);
  });
});
