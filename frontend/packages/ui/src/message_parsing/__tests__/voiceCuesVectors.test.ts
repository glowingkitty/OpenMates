// TS-generated parity vectors for the shared Rust voice-cue stripper.
// The committed JSON (packages/openmates-rust/src/web_parse/voice_cues_ts_vectors.json)
// holds inputs plus outputs of stripVoiceDeliveryCues. This test fails when
// TypeScript drifts from the vectors and prints the regenerated file as
// VECTORS_B64 chunks; the Rust tests (web_parse/voice_cues_tests.rs) replay it.
// Spec: specifications/surfaces/sdk (sdk.client.thin-platform-boundary)
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { stripVoiceDeliveryCues } from "../voiceDeliveryCues";

const VECTORS = resolve(__dirname, "../../../../../../packages/openmates-rust/src/web_parse/voice_cues_ts_vectors.json");

const INPUTS: string[] = [
  "", "plain text", "<!-- voice:curious -->Hi", "a <!--voice:excited--> b", "<!--\tvoice:laughs\n--> x",
  "<!-- voice:short pause -->Then", "<!-- voice:short  pause -->Then", "<!-- voice:Curious -->",
  "<!-- voice:unknown --> kept?", "<!-- voice:whispers --><!-- voice:thoughtful -->x",
  "Useful answer. <!-- voice:cur", "Useful answer. <!-- voice:", "<!-- voice:curious", "<!-- voice:curious -- >",
  "<!-- voice:curious --> tail <!-- voice:exc", "<!-- voice:unknown --> then <!-- voice:curious -->",
  "<!-- voice:x\nnewline --", "<!-- other -->", "<!-- voice:curious --> x　<!--　voice:laughs -->",
  "`<!-- voice:curious -->`", "``a `<!-- voice:laughs -->` b``<!-- voice:laughs -->",
  "`unclosed <!-- voice:curious -->", "```text\n<!-- voice:excited -->\n```\n<!-- voice:excited -->",
  "````markdown\n```\n<!-- voice:excited -->\n````<!-- voice:excited -->", "~~~text\n<!-- voice:laughs -->\n~~~ <!-- voice:laughs -->",
  "~~ <!-- voice:laughs --> ~~", "~~~~ a ~~~ <!-- voice:laughs --> ~~~~ <!-- voice:laughs -->", "~~~ never closed <!-- voice:laughs -->",
  "``a``` <!-- voice:laughs -->", "a ` b <!-- voice:laughs --> c ` d <!-- voice:laughs -->",
  "Read [the guide](https://example.org). <!-- voice:short pause -->Then continue.",
  "café \u{1F600} <!-- voice:curious --> 中文 <!-- voice:exc",
  "<<!-- voice:curious -->", "<!-<!-- voice:curious -->", "a>b <!-- voice:excited --> c>d",
];

describe("voice delivery cue vectors (TypeScript side)", () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it("committed vectors equal the TypeScript stripper", () => {
    const generated = `${JSON.stringify({ strip: INPUTS.map((value) => ({ in: value, out: stripVoiceDeliveryCues(value) })) }, null, 1)}\n`;
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
