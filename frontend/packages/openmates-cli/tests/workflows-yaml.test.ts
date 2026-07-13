/**
 * CLI Workflow YAML command contract tests.
 *
 * Purpose: lock the generated authoring schema and the YAML lifecycle command
 * surface expected by the CLI-first Workflow runtime spec.
 * Security: no network calls; this reads only generated local metadata.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/workflows-yaml.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { workflowAuthoringSchema } from "../src/generated/workflowAuthoringSchema.ts";


describe("Workflow YAML authoring schema", () => {
  it("exposes the approved YAML action and control forms", () => {
    assert.deepEqual(workflowAuthoringSchema.triggers, ["manual", "schedule"]);
    assert.ok(workflowAuthoringSchema.stepForms.includes("use_app_skill"));
    assert.ok(workflowAuthoringSchema.stepForms.includes("send_chat_message"));
    assert.ok(workflowAuthoringSchema.stepForms.includes("ask_for_user_input"));
    assert.ok(workflowAuthoringSchema.stepForms.includes("for_every"));
    assert.ok(workflowAuthoringSchema.stepForms.includes("repeat_until"));
    assert.ok(workflowAuthoringSchema.stepForms.includes("wait"));
    assert.ok(workflowAuthoringSchema.stepForms.includes("if"));
  });
});
