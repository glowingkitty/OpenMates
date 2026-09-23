import assert from "node:assert/strict";
import test from "node:test";
import { createProjectIgnoredReadGrant, verifyProjectIgnoredReadGrant } from "../../ui/src/utils/projectIgnoredReadGrant.js";

// contract-test: supporting surface=cli assertions=projects.files.ignored-exact-inclusion,projects.files.no-server-decryption-authority
test("ignored-read consent is cryptographically bound to one exact source request and expires", async () => {
  const key = crypto.getRandomValues(new Uint8Array(32));
  const scope = { projectId: "project-a", sourceId: "source-a", requestId: "request-a", chatId: "chat-a", operationId: "operation-a", path: "dist/app.js" };
  const expected = { ...scope };
  const now = 1_000_000;
  const grant = await createProjectIgnoredReadGrant(key, scope, now);
  assert.equal(await verifyProjectIgnoredReadGrant(key, grant, expected, now), true);
  for (const [field, replacement] of Object.entries({ projectId: "project-b", sourceId: "source-b", requestId: "request-b", path: "dist/sibling.js", chatId: "chat-b", operationId: "operation-b" })) {
    assert.equal(await verifyProjectIgnoredReadGrant(key, grant, { ...expected, [field]: replacement }, now), false, field);
    assert.equal(await verifyProjectIgnoredReadGrant(key, { ...grant, [field]: replacement }, { ...expected, [field]: replacement }, now), false, `forged ${field}`);
  }
  assert.equal(await verifyProjectIgnoredReadGrant(key, { ...grant, chatId: "chat-b" }, expected, now), false);
  assert.equal(await verifyProjectIgnoredReadGrant(key, { ...grant, operationId: "operation-b" }, expected, now), false);
  assert.equal(await verifyProjectIgnoredReadGrant(crypto.getRandomValues(new Uint8Array(32)), grant, expected, now), false);
  assert.equal(await verifyProjectIgnoredReadGrant(key, grant, expected, grant.expiresAt), false);
  assert.equal(await verifyProjectIgnoredReadGrant(key, { ...grant, expiresAt: grant.expiresAt + 1 }, expected, now), false);
  assert.equal(await verifyProjectIgnoredReadGrant(key, { include_ignored: true }, expected, now), false);
  await assert.rejects(createProjectIgnoredReadGrant(key, { ...scope, path: "dist/../.env" }, now), /invalid_ignored_read_scope/);
  await assert.rejects(createProjectIgnoredReadGrant(key, { ...scope, path: "dist/" }, now), /invalid_ignored_read_scope/);
});
