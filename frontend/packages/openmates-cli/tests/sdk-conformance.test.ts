/** Headless SDK source and cross-language crypto contracts; no product requests. */
// contract-test-file: tooling
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { decryptWithAesGcmCombined, sdkKeyFingerprint } from "../src/sdkCrypto.ts";
import { shouldWaitForTeamAi } from "../src/sdkTeamInvocation.ts";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");

test("headless SDK entry has no runtime CLI, client-session, terminal or subprocess dependency", () => {
  const seen = new Set<string>();
  function visit(file: string): void {
    if (seen.has(file)) return; seen.add(file);
    const source = readFileSync(file, "utf8");
    const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
    function runtimePath(path: string): void {
      assert.ok(!["node:child_process", "child_process"].includes(path), "SDK runtime must not launch a CLI process");
      if (!path.startsWith(".")) return;
      if (path.endsWith(".node")) {
        assert.match(path, /^\.\.\/native\/(linux|darwin|win32)-(arm64|x64)\.node$/);
        return;
      }
      const target = resolve(dirname(file), path.replace(/\.js$/, ".ts"));
      assert.ok(!/\/(?:cli|client|storage|keychain|server|tui[^/]*)\.ts$/.test(target), "SDK runtime must stay independent of CLI state and terminal code");
      if (existsSync(target)) visit(target);
    }
    for (const node of tree.statements) {
      if ((!ts.isImportDeclaration(node) && !ts.isExportDeclaration(node)) || !node.moduleSpecifier || !ts.isStringLiteral(node.moduleSpecifier)) continue;
      if (ts.isImportDeclaration(node) && (node.importClause?.isTypeOnly || node.importClause?.namedBindings && ts.isNamedImports(node.importClause.namedBindings) && node.importClause.namedBindings.elements.every(specifier => specifier.isTypeOnly))) continue;
      if (ts.isExportDeclaration(node) && node.isTypeOnly) continue;
      runtimePath(node.moduleSpecifier.text);
    }
    function dynamicImports(node: ts.Node): void {
      if (ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword || ts.isIdentifier(node.expression) && node.expression.text === "require")) {
        assert.ok(node.arguments.length === 1 && ts.isStringLiteral(node.arguments[0]), "SDK dynamic import targets must be statically reviewable");
        runtimePath((node.arguments[0] as ts.StringLiteral).text);
      }
      ts.forEachChild(node, dynamicImports);
    }
    dynamicImports(tree);
  }
  visit(resolve(root, "frontend/packages/openmates-cli/src/sdk-entry.ts"));
  assert.ok(seen.size > 5, "inspect the transitive shared helper graph");
});

test("SDK Team invocation policy tracks the canonical CLI specialist identities", () => {
  const source = readFileSync(resolve(root, "frontend/packages/openmates-cli/src/client.ts"), "utf8");
  const literal = source.match(/export const MATE_NAMES[^=]*=\s*\{([\s\S]*?)\n\};/)?.[1];
  assert.ok(literal);
  const specialists = [...literal.matchAll(/^\s*([a-z_]+):/gm)].map(match => match[1]);
  assert.ok(specialists.length > 10);
  for (const specialist of specialists) assert.equal(shouldWaitForTeamAi(`@mate:${specialist} please help`, "synthetic-team"), specialist !== "onboarding_support");
  assert.equal(shouldWaitForTeamAi("@mate:invented_specialist hello", "synthetic-team"), false);
  assert.equal(shouldWaitForTeamAi("ordinary conversation", "synthetic-team"), false);
  assert.equal(shouldWaitForTeamAi("@openmates hello", "synthetic-team"), true);
});

test("SDK validates canonical OM fingerprints while preserving the historical Python marker", async () => {
  const fixture = JSON.parse(readFileSync(resolve(root, "tests/sdk-conformance/fixtures/core.json"), "utf8"));
  const vector = fixture.capabilities["crypto.aes-gcm-combined.v1"].vectors[1];
  const key = new Uint8Array(Buffer.from(vector.key_b64, "base64"));
  const bytes = Buffer.from(vector.ciphertext_b64, "base64");
  assert.deepEqual([...bytes.subarray(2, 6)], [...sdkKeyFingerprint(key)]);
  const legacy = Buffer.from(bytes); legacy.set([1, 0, 0, 0], 2);
  assert.equal(await decryptWithAesGcmCombined(legacy.toString("base64"), key), vector.plaintext);
  legacy[legacy.length - 1] ^= 1;
  assert.equal(await decryptWithAesGcmCombined(legacy.toString("base64"), key), null);
  bytes[2] ^= 1;
  assert.equal(await decryptWithAesGcmCombined(bytes.toString("base64"), key), null);
});

test("npm API-key operations emit the shared wire vectors used by Rust and Python", async () => {
  const { runOperationVectors, runMemoryVectors } = await import(resolve(root, "tests/sdk-conformance/runners/sdk-api-key-operations.mjs"));
  const operations = JSON.parse(readFileSync(resolve(root, "tests/sdk-conformance/fixtures/sdk-api-key-operations.json"), "utf8")).capabilities["sdk.api-key-operations.v1"];
  const sdk = await import("../src/sdk.ts");
  const results = await runOperationVectors(operations, sdk);
  assert.equal(results.length, operations.vectors.length);
  const memories = JSON.parse(readFileSync(resolve(root, "tests/sdk-conformance/fixtures/sdk-api-key-memories.json"), "utf8"));
  const crypto = await import("../src/crypto.ts");
  const sdkCrypto = await import("../src/sdkCrypto.ts");
  assert.equal((await runMemoryVectors(memories, crypto, sdkCrypto)).length, memories.vectors.length + memories.hashes.length + 1);
});

test("npm keyManagement and models facades run the shared Rust WASM core or refuse with a typed error", async () => {
  const { keyManagement, models, SessionClientError } = await import("../src/sdk-entry.ts");
  assert.ok(Object.isFrozen(keyManagement) && Object.isFrozen(models));
  const key = new Uint8Array(32).map((_, index) => index);
  if (!existsSync(resolve(root, "frontend/packages/openmates-cli/wasm/openmates_sdk_bg.wasm"))) {
    assert.throws(() => keyManagement.encodeKey(key), (error: unknown) => error instanceof SessionClientError && error.code === "native_binding_unavailable");
    assert.throws(() => models.workspaces(), (error: unknown) => error instanceof SessionClientError && error.code === "native_binding_unavailable");
    return;
  }
  assert.deepEqual([...keyManagement.decodeKey(keyManagement.encodeKey(key))], [...key]);
  assert.equal(keyManagement.decryptCombined(keyManagement.encryptCombined("synthetic plaintext", key), key), "synthetic plaintext");
  assert.throws(() => keyManagement.decodeKey("c2hvcnQ="), (error: unknown) => error instanceof SessionClientError && error.code === "crypto");
  assert.equal(models.workspaces()[0].id, "chats");
  assert.throws(() => models.parseItem({ id: "item-1" }), (error: unknown) => error instanceof SessionClientError && error.code === "invalid_argument");
});
