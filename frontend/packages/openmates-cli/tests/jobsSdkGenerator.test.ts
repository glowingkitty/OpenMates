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
  assert.deepEqual(metadata.schema.properties.countries.default, ["DE"]);
  assert.equal(metadata.schema.properties.countries.maxItems, 2);
  assert.equal(metadata.schema.properties.countries["x-ui"].basic, true);
  assert.equal("default" in metadata.schema.properties.requests.items.properties.country, false);
  assert.equal(metadata.schema.properties.requests.items.properties.countries["x-ui"].basic, false);
  assert.equal(metadata.schema.properties.requests.items.properties.limit.maximum, 50);
  assert.deepEqual(metadata.schema.properties.requests.items.properties.provider.enum, [
    "auto", "Arbeitnow", "Arbeitsagentur", "JobTech", "80,000 Hours", "Hard Problems",
  ]);
  const sdkGroup = metadata.output_schema.properties.results.items.properties;
  assert.equal("title" in sdkGroup, false);
  assert.deepEqual(sdkGroup.country.type, ["string", "null"]);
  assert.equal(sdkGroup.countries.items.type, "string");
  assert.equal(sdkGroup.results.items.properties.title.type, "string");
  const listing = sdkGroup.results.items.properties;
  assert.deepEqual(listing.remote.type, ["boolean", "null"]);
  assert.deepEqual(listing.salary_min.type, ["number", "null"]);
  assert.deepEqual(listing.company.type, ["string", "null"]);
  assert.deepEqual(metadata.output_schema.properties.error.type, ["string", "null"]);

  const calls: unknown[][] = [];
  const response = {
    success: true, error: null,
    results: [{ id: 1, country: null, countries: ["DE", "SE"],
      results: [{ title: "Engineer", country: "DE", remote: null, salary_min: null, company: null }] }],
  };
  const apps = new GeneratedAppSkills(async (...args) => {
    calls.push(args);
    return response;
  });
  const input = { countries: ["DE", "SE"], requests: [{ query: "engineer" }] };
  assert.deepEqual(await apps.jobs.search(input), response);
  assert.deepEqual(calls, [["jobs", "search", input, undefined]]);
});
