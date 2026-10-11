import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { writeFileSync, mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { processFiles } from "../src/fileEmbed.ts";
import { formatEmbedFullscreenLines, renderEmbedPreview } from "../src/embedRenderers.ts";
import type { DecryptedEmbed } from "../src/client.ts";

const testDir = join(tmpdir(), `openmates-diagram-html-${process.pid}`);

describe("HTML diagram file import", () => {
  const source = '<!DOCTYPE html><html data-om-render-width="960" data-om-render-height="560"><head><title>Revenue flow</title></head><body><svg data-om-diagram="flowchart" viewBox="0 0 800 400" xmlns="http://www.w3.org/2000/svg"><g data-om-component="source" data-om-editable="true"><text>Source</text></g></svg></body></html>';

  // contract-test: supporting surface=cli assertions=chats.rendering.assistant-document-convergence
  it("reopens a complete inert exported diagram as source-first content", () => {
    mkdirSync(testDir, { recursive: true });
    const filePath = join(testDir, "revenue.html");
    writeFileSync(filePath, source);
    try {
      const result = processFiles([filePath], null);
      assert.equal(result.errors.length, 0);
      assert.equal(result.embeds[0].embed.type, "diagram_html");
      assert.equal(result.embeds[0].embed.appId, "diagrams");
      assert.equal(result.embeds[0].embed.skillId, "html");
      assert.equal(result.embeds[0].embed.contentHash,
        createHash("sha256").update(source).digest("hex"));
      assert.match(result.embeds[0].embed.content, /Revenue flow/);
      assert.match(result.embeds[0].embed.content, /html_source/);
    } finally { rmSync(testDir, { recursive: true, force: true }); }
  });

  // contract-test: supporting surface=cli assertions=chats.rendering.assistant-document-convergence
  it("keeps executable HTML as generic code", () => {
    mkdirSync(testDir, { recursive: true });
    const filePath = join(testDir, "unsafe.html");
    writeFileSync(filePath, source.replace("</body>", "<script>alert(1)</script></body>"));
    try { assert.equal(processFiles([filePath], null).embeds[0].embed.type, "code-code"); }
    finally { rmSync(testDir, { recursive: true, force: true }); }
  });

  // contract-test: supporting surface=cli assertions=chats.rendering.assistant-document-convergence
  it("recognizes the first-party full HTML/SVG example without rewriting its source", () => {
    const example = join(process.cwd(), "../ui/src/components/embeds/diagrams/diagramHtmlExampleLight.html");
    const result = processFiles([example], null);
    assert.equal(result.errors.length, 0);
    assert.equal(result.embeds[0].embed.type, "diagram_html");
    assert.match(result.embeds[0].embed.content, /architecture/);
    assert.match(result.embeds[0].embed.content, /1240/);
  });
});

function captureStdout(run: () => Promise<void>): Promise<string> {
  let output = "";
  const originalWrite = process.stdout.write.bind(process.stdout);
  process.stdout.write = ((chunk: string | Uint8Array) => { output += chunk.toString(); return true; }) as typeof process.stdout.write;
  return run().then(() => output).finally(() => { process.stdout.write = originalWrite; });
}

describe("HTML diagram terminal rendering", () => {
  // contract-test: supporting surface=cli assertions=chats.rendering.assistant-document-convergence
  it("shows diagram metadata without dumping untrusted HTML", async () => {
    const embed: DecryptedEmbed = {
      id: "diagram-1", embedId: "diagram-123456", type: "diagram_html",
      appId: "diagrams", skillId: "html", textPreview: "Revenue flow", createdAt: null,
      content: { type: "diagram_html", title: "Revenue flow", diagram_kind: "flowchart",
        render_width: 960, render_height: 560, version_number: 2,
        html_source: "<html><script>not printed</script></html>" },
    };
    const preview = await captureStdout(() => renderEmbedPreview(embed, {} as never));
    assert.match(preview, /Revenue flow/);
    assert.match(preview, /flowchart/);
    assert.doesNotMatch(preview, /<script>/);
    const detail = await formatEmbedFullscreenLines(embed, {} as never);
    const joined = Array.isArray(detail) ? detail.join("\n") : String(detail);
    assert.match(joined, /Source: 40 characters|Source: [0-9]+ characters/);
    assert.doesNotMatch(joined, /<script>/);
  });
});
