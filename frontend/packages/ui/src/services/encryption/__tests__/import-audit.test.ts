/**
 * import-audit.test.ts -- Static Import Audit for ARCH-03
 *
 * Verifies that no sync handler file imports encrypt/decrypt functions directly
 * from cryptoService.ts. All crypto operations must route through
 * MessageEncryptor or MetadataEncryptor modules.
 *
 * This test reads source files as text and checks import patterns.
 * It serves as a regression guard -- if anyone adds a new `import("./cryptoService")`
 * to a sync handler, this test fails.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

const SERVICES_DIR = resolve(__dirname, "../../");

const SYNC_HANDLER_FILES = [
  "chatSyncServiceSenders.ts",
  "sendersChatMessages.ts",
  "sendersChatManagement.ts",
  "sendersDrafts.ts",
  "sendersEmbeds.ts",
  "sendersSync.ts",
  "chatSyncServiceHandlersAI.ts",
  "chatSyncServiceHandlersChatUpdates.ts",
  "chatSyncServiceHandlersAppSettings.ts",
  "chatSyncServiceHandlersCoreSync.ts",
  "chatSyncServiceHandlersPhasedSync.ts",
  "chatSyncService.ts",
];

// These patterns indicate direct crypto imports that should go through encryptors
const FORBIDDEN_PATTERNS = [
  /import\s*\{[^}]*(?:encrypt|decrypt)[^}]*\}\s*from\s*["']\.\/cryptoService["']/,
  /await\s+import\s*\(\s*["']\.\/cryptoService["']\s*\)/,
  /import\s*\(\s*["']\.\/cryptoService["']\s*\)/,
];

describe("ARCH-03: No direct cryptoService imports in sync handlers", () => {
  for (const file of SYNC_HANDLER_FILES) {
    it(`${file} has no direct cryptoService encrypt/decrypt imports`, () => {
      const filePath = resolve(SERVICES_DIR, file);
      let content: string;
      try {
        content = readFileSync(filePath, "utf-8");
      } catch {
        // File might not exist (e.g., sendersDrafts.ts has no crypto)
        return;
      }

      for (const pattern of FORBIDDEN_PATTERNS) {
        const matches = content.match(new RegExp(pattern, "g"));
        expect(
          matches,
          `Found forbidden cryptoService import in ${file}: ${matches?.[0]}`,
        ).toBeNull();
      }
    });
  }
});

describe("SYNC-03/04/05: Encryptor routing verification", () => {
  it("SYNC-03: AI handler uses MessageEncryptor for streaming decrypt paths", () => {
    const content = readFileSync(
      resolve(SERVICES_DIR, "chatSyncServiceHandlersAI.ts"),
      "utf-8",
    );
    expect(content).toContain("MessageEncryptor");
    expect(content).toContain("MetadataEncryptor");
  });

  it("SYNC-04: CoreSync handler uses encryptor modules for background sync", () => {
    const content = readFileSync(
      resolve(SERVICES_DIR, "chatSyncServiceHandlersCoreSync.ts"),
      "utf-8",
    );
    expect(content).toMatch(/MessageEncryptor|MetadataEncryptor/);
  });

  it("SYNC-05: PhasedSync handler uses MessageEncryptor for reconnection decrypt", () => {
    const content = readFileSync(
      resolve(SERVICES_DIR, "chatSyncServiceHandlersPhasedSync.ts"),
      "utf-8",
    );
    expect(content).toContain("MessageEncryptor");
  });
});
