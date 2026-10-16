// contract-test-file: tooling
import { test } from "node:test";
import assert from "node:assert/strict";
import { handleWiki } from "../src/cli.ts";
import type { OpenMatesClient } from "../src/client.ts";

async function capture(run: () => Promise<void>): Promise<string[]> {
  const lines: string[] = [];
  const original = console.log;
  console.log = (...args: unknown[]) => { lines.push(args.join(" ")); };
  try { await run(); } finally { console.log = original; }
  return lines;
}

// contract-test: supporting surface=cli assertions=wikipedia-mentions.surfaces.semantic-parity
test("wiki search and show preserve language and canonical title; suggestions failure preserves the article", async () => {
  const calls: unknown[][] = [];
  const client = {
    searchWikipediaTitles: async (...args: unknown[]) => { calls.push(["search", ...args]); return [{ title: "Ada Lovelace" }]; },
    wikipediaSummary: async (...args: unknown[]) => { calls.push(["summary", ...args]); return { title: "Ada Lovelace", extract: "English mathematician", source_url: "https://en.wikipedia.org/wiki/Ada_Lovelace" }; },
    wikipediaLearning: async (...args: unknown[]) => { calls.push(["suggestions", ...args]); throw new Error("temporarily unavailable"); },
  } as unknown as OpenMatesClient;
  const flags = { json: true, language: "de" };
  const search = await capture(() => handleWiki(client, "search", ["Ada", "Lovelace"], flags));
  assert.deepEqual(JSON.parse(search[0]), { results: [{ title: "Ada Lovelace" }] });
  const show = await capture(() => handleWiki(client, "show", ["Ada_Lovelace"], flags));
  assert.equal(JSON.parse(show[0]).extract, "English mathematician");
  assert.equal(JSON.parse(show[0]).suggestions_unavailable, true);
  assert.deepEqual(calls, [["search", "Ada Lovelace", "de"], ["summary", "Ada_Lovelace", "de"], ["suggestions", "Ada Lovelace", "de"]]);
  await assert.rejects(handleWiki(client, "learning", ["Ada Lovelace"], flags), /wiki search.*wiki show/);
});
