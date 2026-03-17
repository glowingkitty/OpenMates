/**
 * Unit tests for CLI argument parsing, blocked paths, and URL derivation.
 *
 * These run without network access — all network calls are expected to throw.
 *
 * Run: node --test --experimental-strip-types tests/cli.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

// Import from compiled dist — the .js extension imports in src/ require the build step
import { deriveAppUrl, MEMORY_TYPE_REGISTRY } from "../dist/index.js";

// ---------------------------------------------------------------------------
// deriveAppUrl
// ---------------------------------------------------------------------------

describe("deriveAppUrl", () => {
  const original = process.env.OPENMATES_APP_URL;
  function reset() {
    if (original === undefined) {
      delete process.env.OPENMATES_APP_URL;
    } else {
      process.env.OPENMATES_APP_URL = original;
    }
  }

  it("maps production API to production web app", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("https://api.openmates.org"),
      "https://openmates.org",
    );
  });

  it("maps dev API to dev web app", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("https://api.dev.openmates.org"),
      "https://app.dev.openmates.org",
    );
  });

  it("maps localhost:8000 to localhost:5173", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("http://localhost:8000"),
      "http://localhost:5173",
    );
  });

  it("falls back to production for unknown API URLs", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("https://api.custom-instance.example.com"),
      "https://openmates.org",
    );
  });

  it("respects OPENMATES_APP_URL env override", () => {
    process.env.OPENMATES_APP_URL = "https://my-custom-app.example.com";
    try {
      assert.strictEqual(
        deriveAppUrl("https://api.openmates.org"),
        "https://my-custom-app.example.com",
      );
    } finally {
      reset();
    }
  });

  it("strips trailing slash from OPENMATES_APP_URL override", () => {
    process.env.OPENMATES_APP_URL = "https://my-custom-app.example.com/";
    try {
      assert.strictEqual(
        deriveAppUrl("https://api.openmates.org"),
        "https://my-custom-app.example.com",
      );
    } finally {
      reset();
    }
  });
});

// ---------------------------------------------------------------------------
// MEMORY_TYPE_REGISTRY
// ---------------------------------------------------------------------------

describe("MEMORY_TYPE_REGISTRY", () => {
  it("contains at least 10 memory types", () => {
    const keys = Object.keys(MEMORY_TYPE_REGISTRY);
    assert.ok(keys.length >= 10, `expected >=10 types, got ${keys.length}`);
  });

  it("every type has appId, itemType, required, and properties", () => {
    for (const [key, def] of Object.entries(MEMORY_TYPE_REGISTRY)) {
      assert.ok(def.appId, `${key}: missing appId`);
      assert.ok(def.itemType, `${key}: missing itemType`);
      assert.ok(
        Array.isArray(def.required),
        `${key}: required should be array`,
      );
      assert.ok(
        typeof def.properties === "object",
        `${key}: properties should be object`,
      );
    }
  });

  it("all required fields are present in properties", () => {
    for (const [key, def] of Object.entries(MEMORY_TYPE_REGISTRY)) {
      for (const req of def.required) {
        assert.ok(
          def.properties[req] !== undefined,
          `${key}: required field '${req}' missing from properties`,
        );
      }
    }
  });

  it("code/preferred_tech requires 'name'", () => {
    const def = MEMORY_TYPE_REGISTRY["code/preferred_tech"];
    assert.ok(def, "code/preferred_tech should exist");
    assert.ok(def.required.includes("name"), "should require 'name'");
  });

  it("ai/communication_style has enum values for 'tone'", () => {
    const def = MEMORY_TYPE_REGISTRY["ai/communication_style"];
    assert.ok(def, "ai/communication_style should exist");
    const tone = def.properties["tone"];
    assert.ok(
      tone?.enum && tone.enum.length > 0,
      "tone should have enum values",
    );
    assert.ok(
      tone.enum!.includes("formal"),
      "tone enum should include 'formal'",
    );
  });

  it("registry key format matches appId/itemType", () => {
    for (const [key, def] of Object.entries(MEMORY_TYPE_REGISTRY)) {
      const expectedKey = `${def.appId}/${def.itemType}`;
      assert.strictEqual(
        key,
        expectedKey,
        `key mismatch: ${key} vs ${expectedKey}`,
      );
    }
  });
});

// ---------------------------------------------------------------------------
// Schema validation (via OpenMatesClient.createMemory validation path)
// In isolation: we test the validation logic that would be called by the client.
// We re-implement a minimal version to keep tests network-free.
// ---------------------------------------------------------------------------

function validateMemory(
  registryKey: string,
  itemValue: Record<string, unknown>,
): { valid: true } | { valid: false; error: string } {
  const schema = MEMORY_TYPE_REGISTRY[registryKey];
  if (!schema) {
    return { valid: false, error: `Unknown type: ${registryKey}` };
  }
  const missing = schema.required.filter(
    (f) =>
      itemValue[f] === undefined ||
      itemValue[f] === null ||
      itemValue[f] === "",
  );
  if (missing.length > 0) {
    return { valid: false, error: `Missing required: ${missing.join(", ")}` };
  }
  for (const [field, def] of Object.entries(schema.properties)) {
    const val = itemValue[field];
    if (val !== undefined && def.enum && !def.enum.includes(String(val))) {
      return {
        valid: false,
        error: `Invalid enum value '${String(val)}' for '${field}'`,
      };
    }
  }
  return { valid: true };
}

describe("memory schema validation", () => {
  it("accepts valid code/preferred_tech entry", () => {
    const result = validateMemory("code/preferred_tech", {
      name: "Python",
      proficiency: "advanced",
    });
    assert.ok(result.valid);
  });

  it("rejects missing required field", () => {
    const result = validateMemory("code/preferred_tech", {
      proficiency: "advanced",
    });
    assert.ok(!result.valid);
    assert.ok(result.valid === false && result.error.includes("name"));
  });

  it("rejects invalid enum value", () => {
    const result = validateMemory("code/preferred_tech", {
      name: "Python",
      proficiency: "guru",
    });
    assert.ok(!result.valid);
    assert.ok(result.valid === false && result.error.includes("guru"));
  });

  it("accepts valid ai/communication_style entry", () => {
    const result = validateMemory("ai/communication_style", {
      title: "Work Mode",
      tone: "professional",
      verbosity: "detailed",
    });
    assert.ok(result.valid);
  });

  it("rejects unknown memory type", () => {
    const result = validateMemory("fake/nonexistent", { name: "x" });
    assert.ok(!result.valid);
    assert.ok(result.valid === false && result.error.includes("Unknown"));
  });

  it("accepts entry with optional fields omitted", () => {
    const result = validateMemory("books/favorite_books", { title: "Dune" });
    assert.ok(result.valid);
  });
});
