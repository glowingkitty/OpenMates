#!/usr/bin/env node

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { after } from "node:test";

process.env.OPENMATES_PROJECT_ROOT ||= "/home/superdev/projects/OpenMates";
const { OpenMatesHooks } = await import("../../.opencode/plugins/openmates-hooks.js");
const {
  assistantTextPartForTest,
  mediaDeliveryPromptForTest,
  responseContainsMediaForTest,
  responseMediaArtifactForTest,
} = OpenMatesHooks.test;
const source = readFileSync(new URL("../../.opencode/plugins/openmates-hooks.js", import.meta.url), "utf8");
const tempRoot = mkdtempSync("/tmp/openmates-response-media-");
after(() => rmSync(tempRoot, { recursive: true, force: true }));

test("video output becomes one exact pending artifact", () => {
  const snippet = '<video controls><source src="https://media.example/proof.mp4" type="video/mp4"></video>';
  const first = responseMediaArtifactForTest({
    command: "python3 scripts/tests.py run --spec map.spec.ts",
    output: `run failed after capture\n${snippet}`,
    automationEnabled: true,
  });
  const repeated = responseMediaArtifactForTest({
    command: "python3 scripts/tests.py run --spec map.spec.ts",
    output: snippet,
    automationEnabled: true,
  });

  assert.equal(first.artifact_type, "video");
  assert.equal(first.snippet, snippet);
  assert.equal(first.artifact_key, repeated.artifact_key);
  assert.match(mediaDeliveryPromptForTest(first, { automationEnabled: true }), /even when the result is visibly broken/);
  assert.equal(responseContainsMediaForTest(`Progress\n${snippet}`, first), true);
});

test("escaped and unescaped video snippets use one delivery key", () => {
  const normal = '<video controls crossorigin="anonymous"><source src="https://media.example/video.webm?x=1&amp;y=2" type="video/webm"></video>';
  const escaped = '<video controls crossorigin=\\"anonymous\\"><source src="https://media.example/video.webm?x=1&amp;y=2" type=\\"video/webm\\"></video>';
  const first = responseMediaArtifactForTest({
    command: "python3 scripts/tests.py run --spec map.spec.ts",
    output: normal,
    automationEnabled: true,
  });
  const second = responseMediaArtifactForTest({
    command: "python3 scripts/tests.py run --spec map.spec.ts",
    output: escaped,
    automationEnabled: true,
  });

  assert.equal(first.artifact_key, second.artifact_key);
  assert.equal(responseContainsMediaForTest(`Progress\n${normal}`, second), true);
});

test("Figma exports and uploaded images retain one frame identity", () => {
  const path = "test-results/figma/settings-ai.png";
  const absolutePath = join(tempRoot, path);
  mkdirSync(join(tempRoot, "test-results/figma"), { recursive: true });
  writeFileSync(absolutePath, "png");
  const exported = responseMediaArtifactForTest({
    command: "python3 scripts/download_figma_images.py",
    output: `exported ${path}`,
    cwd: tempRoot,
    requireExistingFigmaExport: true,
    automationEnabled: true,
  });
  const uploaded = responseMediaArtifactForTest({
    command: `python3 scripts/opencode_response_media.py ${exported.artifact_path} --alt Figma`,
    output: "![Figma reference](https://media.example/settings.png)",
    cwd: tempRoot,
    requireExistingFigmaExport: true,
    automationEnabled: true,
  });

  assert.equal(exported.artifact_type, "figma_export");
  assert.equal(exported.artifact_path, absolutePath);
  assert.equal(uploaded.artifact_type, "figma_image");
  assert.equal(uploaded.artifact_key, exported.artifact_key);
  assert.equal(mediaDeliveryPromptForTest(exported, { automationEnabled: true }), "");
  assert.match(mediaDeliveryPromptForTest(uploaded, { automationEnabled: true }), /Include this exact snippet/);
});

test("missing Figma exports are not queued when delivery requires a real file", () => {
  const artifact = responseMediaArtifactForTest({
    command: "python3 scripts/download_figma_images.py",
    output: "exported test-results/figma/missing.png",
    cwd: tempRoot,
    requireExistingFigmaExport: true,
    automationEnabled: true,
  });

  assert.equal(artifact, null);
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
