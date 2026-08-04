/**
 * Real dev-server npm SDK Project verification.
 *
 * Runs the shared temporary-key harness for Personal and Team encrypted CRUD.
 * The harness owns credential creation, device approval, cleanup, and revocation.
 * No remote filesystem methods or cleartext fixture values are emitted.
 */

import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { it } from "node:test";

it("runs Personal and Team npm Project CRUD against dev", { timeout: 180_000 }, () => {
  const root = resolve(import.meta.dirname, "../../../..");
  execFileSync(
    "node",
    [
      "--experimental-strip-types",
      "--loader",
      "./frontend/packages/openmates-cli/tests/loader.mjs",
      "scripts/verify_sdk_projects_live_smoke.mjs",
      "--npm",
    ],
    { cwd: root, env: process.env, stdio: "inherit" },
  );
});
