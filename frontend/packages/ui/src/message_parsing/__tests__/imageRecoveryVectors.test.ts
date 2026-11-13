// TS-generated parity vectors for the shared Rust generated-image recovery.
// The committed JSON (packages/openmates-rust/src/web_parse/image_recovery_ts_vectors.json)
// holds sources, resolved parents and the outputs of lostImageParents /
// recoverGeneratedImageDocument. This test fails when TypeScript drifts from the
// vectors and prints the regenerated file as VECTORS_B64 chunks; the Rust tests
// (web_parse/image_recovery_tests.rs) replay it.
// Spec: specifications/surfaces/sdk (sdk.client.thin-platform-boundary)
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { lostImageParents, recoverGeneratedImageDocument } from "../generatedImageRecovery";
import type { AssistantDocument } from "../assistantActivityRuns";

const VECTORS = resolve(__dirname, "../../../../../../packages/openmates-rust/src/web_parse/image_recovery_ts_vectors.json");

const P1 = "11111111-1111-4111-8111-111111111111";
const P2 = "AAAAAAAA-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const C1 = "22222222-2222-4222-8222-222222222222";
const C2 = "33333333-3333-4333-8333-333333333333";
const C3 = "44444444-4444-4444-8444-444444444444";

const skill = (attrs: Record<string, unknown>) => ({ type: "paragraph", content: [{ type: "embed", attrs: { type: "app-skill-use", app_id: "images", skill_id: "generate", ...attrs } }] });
const bang = (text = "!\n!") => ({ type: "paragraph", content: [{ type: "text", text }] });
const doc = (...content: unknown[]) => ({ type: "doc", content });
const parent = (extra: Record<string, unknown> = {}) => ({ app_id: "images", skill_id: "generate", status: "finished", embed_ids: [C1, C2], ...extra });
const preview = (attrs: Record<string, unknown>) => ({ type: "embedPreviewLarge", attrs });

interface Case { name: string; source: unknown; resolved: Record<string, unknown> }
const CASES: Case[] = [
  { name: "two children", source: doc(skill({ id: P1 }), bang()), resolved: { [P1]: parent() } },
  { name: "draft skill and contentRef", source: doc(skill({ contentRef: `embed:${P1}`, skill_id: "generate_draft" }), bang(" ! ")), resolved: { [P1]: parent({ skill_id: "generate_draft" }) } },
  { name: "visible sibling kept", source: doc(skill({ id: P1 }), bang(), preview({ embedRef: "generated-images-222222222222" })), resolved: { [P1]: parent() } },
  { name: "all visible", source: doc(skill({ id: P1 }), bang(), preview({ embedId: C1 }), preview({ embedRef: "embed:" + C2 })), resolved: { [P1]: parent() } },
  { name: "ordinary exclamation", source: doc(skill({ id: P1 }), bang("Looks great!")), resolved: { [P1]: parent() } },
  { name: "no placeholder", source: doc(skill({ id: P1 })), resolved: { [P1]: parent() } },
  { name: "unresolved parent", source: doc(skill({ id: P1 }), bang()), resolved: {} },
  { name: "processing parent", source: doc(skill({ id: P1 }), bang()), resolved: { [P1]: parent({ status: "processing" }) } },
  { name: "wrong app", source: doc(skill({ id: P1 }), bang()), resolved: { [P1]: parent({ app_id: "web" }) } },
  { name: "invented child id", source: doc(skill({ id: P1 }), bang()), resolved: { [P1]: parent({ embed_ids: ["invented", "", 4, null] }) } },
  { name: "no embed_ids", source: doc(skill({ id: P1 }), bang()), resolved: { [P1]: { app_id: "images", skill_id: "generate", status: "finished" } } },
  { name: "other app skill ignored", source: doc(skill({ id: P1, app_id: "web" }), bang()), resolved: { [P1]: parent() } },
  { name: "non uuid id", source: doc(skill({ id: "not-a-uuid" }), bang()), resolved: {} },
  { name: "duplicate and second parent", source: doc(skill({ id: P1 }), skill({ id: P1 }), skill({ id: P2 }), bang()), resolved: { [P1]: parent(), [P2]: parent({ embed_ids: [C2, C3] }) } },
  { name: "grouped items", source: doc({ type: "paragraph", content: [{ type: "embed", attrs: { type: "app-skill-use-group", groupedItems: [{ app_id: "images", skill_id: "generate", id: P1 }, { app_id: "web", skill_id: "search", id: P2 }] } }] }, bang()), resolved: { [P1]: parent() } },
  { name: "non doc", source: { type: "paragraph", content: [] }, resolved: {} },
  { name: "unicode whitespace bang", source: doc(skill({ id: P1 }), bang("! !　"), { type: "paragraph", content: [{ type: "text", text: "!" }, { type: "text", text: "\t" }] }), resolved: { [P1]: parent() } },
  { name: "extra source fields preserved", source: { ...doc(skill({ id: P1 }), bang()), meta: { a: 1 } }, resolved: { [P1]: parent() } },
];

async function generate(): Promise<string> {
  const cases = [];
  for (const c of CASES) {
    const parents = lostImageParents(c.source);
    const document = await recoverGeneratedImageDocument(c.source as AssistantDocument, async (id) => (c.resolved[id] as Record<string, unknown> | undefined) ?? null);
    cases.push({ name: c.name, source: c.source, resolved: c.resolved, parents, document });
  }
  return `${JSON.stringify({ cases }, null, 1)}\n`;
}

describe("generated image recovery vectors (TypeScript side)", () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it("committed vectors equal the TypeScript recovery", async () => {
    const generated = await generate();
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
