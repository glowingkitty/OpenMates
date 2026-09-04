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
  // contract-test: supporting surface=sdks.npm assertions=audio-generate.surface-parity,audio-speak.surface-parity
  it("includes native audio, web, design, images, models3d, business, and fitness metadata", () => {
    const audioGenerate = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "audio" && skill.skill_id === "generate",
    );
    const audioSpeak = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "audio" && skill.skill_id === "speak",
    );
    const webSearch = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "web" && skill.skill_id === "search",
    );
    const imageGenerate = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "images" && skill.skill_id === "generate",
    );
    const designSearchIcons = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "design" && skill.skill_id === "search_icons",
    );
    const codeRun = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "code" && skill.skill_id === "run",
    );
    const models3dGenerate = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "models3d" && skill.skill_id === "generate",
    );
    const models3dSearch = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "models3d" && skill.skill_id === "search",
    );
    const businessFinancials = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "business" && skill.skill_id === "company_financials",
    );
    const fitnessLocations = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "fitness" && skill.skill_id === "search_locations",
    );
    const fitnessClasses = APP_SKILL_METADATA.find(
      (skill) => skill.app_id === "fitness" && skill.skill_id === "search_classes",
    );

    assert.ok(audioGenerate);
    assert.equal(audioGenerate.app_namespace_ts, "audio");
    assert.equal(audioGenerate.skill_method_ts, "generate");
    assert.deepEqual(
      audioGenerate.schema.properties.requests.items.properties.provider.enum,
      ["elevenlabs"],
    );

    assert.ok(audioSpeak);
    assert.equal(audioSpeak.app_namespace_ts, "audio");
    assert.equal(audioSpeak.skill_method_ts, "speak");
    assert.deepEqual(
      audioSpeak.schema.properties.requests.items.properties.voice.enum,
      ["warm_neutral", "bright_neutral", "calm_narrator"],
    );
    assert.deepEqual(
      audioSpeak.schema.properties.requests.items.properties.model.enum,
      ["eleven_v3", "eleven_multilingual_v2", "eleven_flash_v2_5"],
    );
    assert.equal(audioSpeak.schema.properties.requests.items.properties.model.default, "eleven_v3");

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

    assert.ok(codeRun);
    assert.equal(codeRun.app_namespace_ts, "code");
    assert.equal(codeRun.skill_method_ts, "run");
    assert.equal(codeRun.schema.properties.requests.items.properties.mode.default, "direct");
    assert.ok(codeRun.schema.properties.requests.items.properties.files.items.properties.content_base64);
    assert.equal(
      codeRun.output_schema.properties.results.items.properties.final.properties.artifacts.items.properties.download_url.type,
      "string",
    );

    assert.equal(models3dGenerate, undefined);

    assert.ok(models3dSearch);
    assert.equal(models3dSearch.app_namespace_ts, "models3d");
    assert.equal(models3dSearch.skill_method_ts, "search");
    assert.ok(models3dSearch.schema.properties.requests);

    assert.ok(businessFinancials);
    assert.equal(businessFinancials.app_namespace_ts, "business");
    assert.equal(businessFinancials.skill_method_ts, "companyFinancials");
    assert.ok(businessFinancials.schema.properties.companies);

    assert.ok(fitnessLocations);
    assert.equal(fitnessLocations.app_namespace_ts, "fitness");
    assert.equal(fitnessLocations.skill_method_ts, "searchLocations");
    assert.ok(fitnessLocations.schema.properties.requests);

    assert.ok(fitnessClasses);
    assert.equal(fitnessClasses.app_namespace_ts, "fitness");
    assert.equal(fitnessClasses.skill_method_ts, "searchClasses");
    assert.ok(fitnessClasses.schema.properties.requests);
  });

  // contract-test: supporting surface=sdks.npm assertions=audio-generate.surface-parity,audio-speak.surface-parity
  it("delegates native methods to the app-skill runner", async () => {
    const calls: unknown[] = [];
    const apps = new GeneratedAppSkills(async (appId, skillId, input, options) => {
      calls.push({ appId, skillId, input, options });
      return { ok: true };
    });

    const result = await apps.web.search({ requests: [{ query: "hello" }] });
    const audioResult = await apps.audio.generate({ requests: [{ prompt: "soft tick", provider: "elevenlabs" }] });
    const speechResult = await apps.audio.speak({ requests: [{ text: "Welcome back.", provider: "elevenlabs" }] });
    const iconResult = await apps.design.searchIcons({ requests: [{ query: "home" }] });
    const codeRunResult = await apps.code.run({ requests: [{ mode: "direct", entry_path: "main.py", files: [] }] });
    const fitnessResult = await apps.fitness.searchClasses({ requests: [{ address: "Sorauer Str. 12" }] });
    const modelSearchResult = await apps.models3d.search({ requests: [{ query: "benchy" }] });
    const businessResult = await apps.business.companyFinancials(
      { companies: [{ query: "CALM" }] },
      { promptInjectionProtection: false },
    );
    assert.deepEqual(result, { ok: true });
    assert.deepEqual(audioResult, { ok: true });
    assert.deepEqual(speechResult, { ok: true });
    assert.deepEqual(iconResult, { ok: true });
    assert.deepEqual(codeRunResult, { ok: true });
    assert.deepEqual(fitnessResult, { ok: true });
    assert.deepEqual(modelSearchResult, { ok: true });
    assert.deepEqual(businessResult, { ok: true });
    assert.deepEqual(calls, [
      { appId: "web", skillId: "search", input: { requests: [{ query: "hello" }] }, options: undefined },
      { appId: "audio", skillId: "generate", input: { requests: [{ prompt: "soft tick", provider: "elevenlabs" }] }, options: undefined },
      { appId: "audio", skillId: "speak", input: { requests: [{ text: "Welcome back.", provider: "elevenlabs" }] }, options: undefined },
      { appId: "design", skillId: "search_icons", input: { requests: [{ query: "home" }] }, options: undefined },
      { appId: "code", skillId: "run", input: { requests: [{ mode: "direct", entry_path: "main.py", files: [] }] }, options: undefined },
      { appId: "fitness", skillId: "search_classes", input: { requests: [{ address: "Sorauer Str. 12" }] }, options: undefined },
      { appId: "models3d", skillId: "search", input: { requests: [{ query: "benchy" }] }, options: undefined },
      {
        appId: "business",
        skillId: "company_financials",
        input: { companies: [{ query: "CALM" }] },
        options: { promptInjectionProtection: false },
      },
    ]);
  });
});
