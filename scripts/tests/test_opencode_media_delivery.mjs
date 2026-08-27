#!/usr/bin/env node

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

process.env.OPENMATES_PROJECT_ROOT ||= "/home/superdev/projects/OpenMates";
const { OpenMatesHooks } = await import("../../.opencode/plugins/openmates-hooks.js");
const {
  assistantTextPartForTest,
  mediaDeliveryPromptForTest,
  responseContainsMediaForTest,
  responseMediaArtifactForTest,
} = OpenMatesHooks.test;
const source = readFileSync(new URL("../../.opencode/plugins/openmates-hooks.js", import.meta.url), "utf8");

test("video output becomes one exact pending artifact", () => {
  const snippet = '<video controls src="https://media.example/proof.mp4"></video>';
  const first = responseMediaArtifactForTest({
    command: "python3 scripts/tests.py run --spec map.spec.ts",
    output: `run failed after capture\n${snippet}`,
  });
  const repeated = responseMediaArtifactForTest({
    command: "python3 scripts/tests.py run --spec map.spec.ts",
    output: snippet,
  });

  assert.equal(first.artifact_type, "video");
  assert.equal(first.snippet, snippet);
  assert.equal(first.artifact_key, repeated.artifact_key);
  assert.match(mediaDeliveryPromptForTest(first), /even when the result is visibly broken/);
  assert.equal(responseContainsMediaForTest(`Progress\n${snippet}`, first), true);
});

test("Figma exports and uploaded images retain one frame identity", () => {
  const path = "test-results/figma/settings-ai.png";
  const exported = responseMediaArtifactForTest({
    command: "python3 scripts/download_figma_images.py",
    output: `exported ${path}`,
  });
  const uploaded = responseMediaArtifactForTest({
    command: `python3 scripts/opencode_response_media.py ${path} --alt Figma`,
    output: "![Figma reference](https://media.example/settings.png)",
  });

  assert.equal(exported.artifact_type, "figma_export");
  assert.equal(uploaded.artifact_type, "figma_image");
  assert.equal(uploaded.artifact_key, exported.artifact_key);
  assert.match(mediaDeliveryPromptForTest(exported), /opencode_response_media\.py/);
});

test("unrelated tool output creates no artifact", () => {
  assert.equal(responseMediaArtifactForTest({ command: "pytest -q", output: "10 passed" }), null);
});

test("assistant text parts are keyed for completion acknowledgement", () => {
  const part = assistantTextPartForTest({
    type: "message.part.updated",
    properties: { part: { id: "part-1", messageID: "msg-1", type: "text", text: "progress" } },
  });
  assert.deepEqual(part, { messageID: "msg-1", partID: "part-1", text: "progress" });
  assert.equal(assistantTextPartForTest({ type: "message.part.updated", properties: { part: { type: "tool" } } }), null);
});

test("automatic media delivery is asynchronous and single-flight", () => {
  assert.match(source, /automaticDeliverySessions\.has\(sessionID\)/);
  assert.match(source, /client\.session\.promptAsync\(\{/);
  assert.doesNotMatch(source, /client\.session\.prompt\(\{/);
  assert.match(source, /automaticDeliverySessions\.delete\(sessionID\)/);
});
