// frontend/packages/ui/src/components/signup/loginProfileHydration.test.ts
// Guards all login profile hydration paths used by authenticated UI services.
// Every successful user-data path must copy the backend id into userProfile.user_id.
// Without it, chat model preferences and other user-scoped features silently skip sync.
// This static contract covers duplicated success-path profile objects across components.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const components = [
  { path: "../PasswordAndTfaOtp.svelte", expectedProfileBlocks: 3 },
  { path: "../EnterBackupCode.svelte", expectedProfileBlocks: 1 },
  { path: "../EnterRecoveryKey.svelte", expectedProfileBlocks: 1 },
  { path: "../Login.svelte", expectedProfileBlocks: 2 },
];

describe("login profile hydration", () => {
  // contract-test: supporting surface=gui.web assertions=auth.login.method-convergence
  it.each(components)("maps the authenticated user id in every $path profile update", ({ path, expectedProfileBlocks }) => {
    const componentSource = readFileSync(new URL(path, import.meta.url), "utf8");
    const profileBlocks = Array.from(
      componentSource.matchAll(/const userProfileData = \{([\s\S]*?)\n\s*\};/g),
    );

    expect(profileBlocks).toHaveLength(expectedProfileBlocks);
    for (const block of profileBlocks) {
      expect(block[1]).toMatch(/user_id: (?:data\.user|userData)\.id \|\| null/);
    }
  });
});
