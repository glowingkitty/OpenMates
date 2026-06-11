/**
 * Unit tests for CLI URL embed preprocessing.
 *
 * The CLI must match the browser sender behavior: plain URLs in user messages
 * become encrypted website embeds plus markdown embed references before the
 * message is persisted or exported as an example chat.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { prepareUrlEmbeds } from "../src/urlEmbed.ts";

describe("prepareUrlEmbeds", () => {
  it("replaces standalone URLs with website embed references carrying URL fallback", () => {
    const result = prepareUrlEmbeds(
      "Read https://openai.com/index/hello-gpt-4o/ and summarize it.",
    );

    assert.equal(result.embeds.length, 1);
    assert.equal(result.embeds[0]?.type, "web-website");
    const content = result.embeds[0]?.content ?? "";
    const ref = content.match(/^embed_ref:\s*"?([^\n"]+)"?\s*$/m)?.[1];
    assert.match(content, /url: "https:\/\/openai\.com\/index\/hello-gpt-4o\/"/);
    assert.ok(ref, "website embed content must include embed_ref");
    assert.match(result.message, new RegExp(`\\[!\\]\\(embed:${ref}\\)`));
    assert.doesNotMatch(result.message, /```json\n/);
    assert.doesNotMatch(result.message, /"embed_id": "/);
    assert.doesNotMatch(result.message, /^Read https:\/\/openai\.com/m);
  });

  it("does not rewrite URLs inside fenced code blocks", () => {
    const result = prepareUrlEmbeds(
      "```text\nhttps://example.com/inside-code\n```\nOutside https://example.com/page.",
    );

    assert.equal(result.embeds.length, 1);
    assert.match(result.message, /https:\/\/example\.com\/inside-code/);
    assert.match(result.message, /\[!\]\(embed:/);
    assert.doesNotMatch(result.message, /```json\n/);
  });
});
