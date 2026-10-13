/** Generated npm Jobs search facade contract. */

import { it } from "node:test";
import assert from "node:assert/strict";

import { APP_SKILL_METADATA, GeneratedAppSkills } from "../src/generated/appSkills.ts";

// contract-test: supporting surface=sdks.npm assertions=app-skills.surface.semantic-parity
it("exposes jobs.search with Germany default, bounded results, and a direct runner", async () => {
  const metadata = APP_SKILL_METADATA.find(
    (item) => item.app_id === "jobs" && item.skill_id === "search",
  );
  assert.ok(metadata);
  assert.equal(metadata.schema.properties.requests.items.properties.country.default, "DE");
  assert.equal(metadata.schema.properties.requests.items.properties.limit.maximum, 50);
  const sdkGroup = metadata.output_schema.properties.results.items.properties;
  assert.equal("title" in sdkGroup, false);
  assert.equal(sdkGroup.results.items.properties.title.type, "string");
  const listing = sdkGroup.results.items.properties;
  assert.deepEqual(listing.remote.type, ["boolean", "null"]);
  assert.deepEqual(listing.salary_min.type, ["number", "null"]);
  assert.deepEqual(listing.company.type, ["string", "null"]);
  assert.deepEqual(metadata.output_schema.properties.error.type, ["string", "null"]);

  const calls: unknown[][] = [];
  const response = {
    success: true, error: null,
    results: [{ id: 1, results: [{ title: "Engineer", remote: null, salary_min: null, company: null }] }],
  };
  const apps = new GeneratedAppSkills(async (...args) => {
    calls.push(args);
    return response;
  });
  const input = { requests: [{ query: "engineer", country: "SE", provider: "JobTech" }] };
  assert.deepEqual(await apps.jobs.search(input), response);
  assert.deepEqual(calls, [["jobs", "search", input, undefined]]);
});
