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
  it("includes native web search, design icon search, images generate, models3d search, and fitness metadata", () => {
    const webSearch = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "web" && skill.skill_id === "search",
    );
    const imageGenerate = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "images" && skill.skill_id === "generate",
    );
    const designSearchIcons = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "design" && skill.skill_id === "search_icons",
    );
    const models3dGenerate = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "models3d" && skill.skill_id === "generate",
    );
    const models3dSearch = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "models3d" && skill.skill_id === "search",
    );
    const fitnessLocations = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "fitness" && skill.skill_id === "search_locations",
    );
    const fitnessClasses = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "fitness" && skill.skill_id === "search_classes",
    );

    assert.ok(webSearch);
    assert.equal(webSearch.app_namespace_ts, "web");
    assert.equal(webSearch.skill_method_ts, "search");
    assert.equal(webSearch.description_key, "app_skills.web.search.description");
    assert.ok(webSearch.schema.properties.requests);

    assert.ok(imageGenerate);
    assert.equal(imageGenerate.app_namespace_ts, "images");
    assert.equal(imageGenerate.skill_method_ts, "generate");

    assert.ok(designSearchIcons);
    assert.equal(designSearchIcons.app_namespace_ts, "design");
    assert.equal(designSearchIcons.skill_method_ts, "searchIcons");
    assert.ok(designSearchIcons.schema.properties.requests);

    assert.equal(models3dGenerate, undefined);

    assert.ok(models3dSearch);
    assert.equal(models3dSearch.app_namespace_ts, "models3d");
    assert.equal(models3dSearch.skill_method_ts, "search");
    assert.ok(models3dSearch.schema.properties.requests);

    assert.ok(fitnessLocations);
    assert.equal(fitnessLocations.app_namespace_ts, "fitness");
    assert.equal(fitnessLocations.skill_method_ts, "searchLocations");
    assert.ok(fitnessLocations.schema.properties.requests);

    assert.ok(fitnessClasses);
    assert.equal(fitnessClasses.app_namespace_ts, "fitness");
    assert.equal(fitnessClasses.skill_method_ts, "searchClasses");
    assert.ok(fitnessClasses.schema.properties.requests);
  });

  it("delegates native methods to the app-skill runner", async () => {
    const calls: unknown[] = [];
    const apps = new GeneratedAppSkills(async (appId, skillId, input, options) => {
      calls.push({ appId, skillId, input, options });
      return { ok: true };
    });

    const result = await apps.web.search({ requests: [{ query: "hello" }] }, { promptInjectionProtection: false });
    const iconResult = await apps.design.searchIcons({ requests: [{ query: "home" }] });
    const fitnessResult = await apps.fitness.searchClasses({ requests: [{ address: "Sorauer Str. 12" }] });
    const modelSearchResult = await apps.models3d.search({ requests: [{ query: "benchy" }] });
    assert.deepEqual(result, { ok: true });
    assert.deepEqual(iconResult, { ok: true });
    assert.deepEqual(fitnessResult, { ok: true });
    assert.deepEqual(modelSearchResult, { ok: true });
    assert.deepEqual(calls, [
      { appId: "web", skillId: "search", input: { requests: [{ query: "hello" }] }, options: { promptInjectionProtection: false } },
      { appId: "design", skillId: "search_icons", input: { requests: [{ query: "home" }] }, options: undefined },
      { appId: "fitness", skillId: "search_classes", input: { requests: [{ address: "Sorauer Str. 12" }] }, options: undefined },
      { appId: "models3d", skillId: "search", input: { requests: [{ query: "benchy" }] }, options: undefined },
    ]);
  });
});
