/**
 * Unit tests for CLI URL embed preprocessing.
 *
 * The CLI must match the browser sender behavior: plain URLs in user messages
 * become encrypted website embeds plus JSON embed references before the message
 * is persisted or exported as an example chat.
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
    assert.match(result.embeds[0]?.content ?? "", /url: "https:\/\/openai\.com\/index\/hello-gpt-4o\/"/);
    assert.match(result.message, /```json\n/);
    assert.match(result.message, /"type": "website"/);
    assert.match(result.message, /"embed_id": "/);
    assert.match(result.message, /"url": "https:\/\/openai\.com\/index\/hello-gpt-4o\/"/);
    assert.doesNotMatch(result.message, /^Read https:\/\/openai\.com/m);
  });

  it("does not rewrite URLs inside fenced code blocks", () => {
    const result = prepareUrlEmbeds(
      "```text\nhttps://example.com/inside-code\n```\nOutside https://example.com/page.",
    );

    assert.equal(result.embeds.length, 1);
    assert.match(result.message, /https:\/\/example\.com\/inside-code/);
    assert.match(result.message, /"url": "https:\/\/example\.com\/page"/);
  });
});
