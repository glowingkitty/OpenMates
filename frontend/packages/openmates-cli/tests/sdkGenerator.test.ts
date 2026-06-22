/**
 * OpenMates npm SDK generator contract tests.
 *
 * Purpose: verify native app-skill SDK methods are generated from app metadata.
 * Architecture: docs/specs/sdk-cli-parity-v1/spec.yml.
 * Security: generated wrappers only delegate to API-key SDK request helpers.
 * Run: node --test --experimental-strip-types tests/sdkGenerator.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

const { APP_SKILL_METADATA, GeneratedAppSkills } = await import("../src/generated/appSkills.ts");

describe("generated npm SDK app skills", () => {
  it("includes native web search and images generate metadata", () => {
    const webSearch = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "web" && skill.skill_id === "search",
    );
    const imageGenerate = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "images" && skill.skill_id === "generate",
    );

    assert.ok(webSearch);
    assert.equal(webSearch.app_namespace_ts, "web");
    assert.equal(webSearch.skill_method_ts, "search");
    assert.equal(webSearch.description_key, "app_skills.web.search.description");
    assert.ok(webSearch.schema.properties.requests);

    assert.ok(imageGenerate);
    assert.equal(imageGenerate.app_namespace_ts, "images");
    assert.equal(imageGenerate.skill_method_ts, "generate");
  });

  it("delegates native methods to the app-skill runner", async () => {
    const calls: unknown[] = [];
    const apps = new GeneratedAppSkills(async (appId, skillId, input) => {
      calls.push({ appId, skillId, input });
      return { ok: true };
    });

    const result = await apps.web.search({ requests: [{ query: "hello" }] });
    assert.deepEqual(result, { ok: true });
    assert.deepEqual(calls, [
      { appId: "web", skillId: "search", input: { requests: [{ query: "hello" }] } },
    ]);
  });
});
