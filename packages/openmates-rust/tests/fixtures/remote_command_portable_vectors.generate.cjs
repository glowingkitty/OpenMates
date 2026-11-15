// Test-only oracle: reproduces `canonicalPortableRemoteCommandRequest` and
// `remoteCommandPortableRequestDigest` from
// frontend/packages/openmates-cli/src/remoteCommandClient.ts with node, so the
// Rust portable-request canonicalizer is vector-tested for byte compatibility.
// Run: node remote_command_portable_vectors.generate.cjs
const { createHmac } = require("node:crypto");
const { writeFileSync } = require("node:fs");
const { join } = require("node:path");

function canonical(request) {
  return JSON.stringify({
    protocol_version: 1,
    execution_id: request.execution_id,
    chat_id: request.chat_id,
    project_id: request.project_id,
    source_id: request.source_id,
    policy: {
      argv: request.policy.argv,
      cwd: request.policy.cwd,
      mode: request.policy.mode,
      source_access: request.policy.source_access,
      deadline_ms: request.policy.deadline_ms,
      writable_profiles: request.policy.writable_profiles,
      network_profile: request.policy.network_profile,
      credential_profiles: request.policy.credential_profiles,
    },
    approval: request.approval.kind === "one_run" ? { kind: "one_run" } : {
      kind: "preset", preset_id: request.approval.preset_id, definition_digest: request.approval.definition_digest,
    },
  });
}
const key = Buffer.from(Array.from({ length: 32 }, (_, index) => index));
function digest(request) {
  const identity = JSON.stringify(["openmates-remote-command-request-v1", canonical(request)]);
  return createHmac("sha256", key).update(identity).digest("base64url");
}
const base = { execution_id: "exec-1", chat_id: "chat-1", project_id: "project-1", source_id: "source-1" };
const requests = [
  { ...base, policy: { argv: ["cargo", "test"], cwd: ".", mode: "foreground", source_access: "read_only", deadline_ms: 60000, writable_profiles: [], network_profile: null, credential_profiles: [] }, approval: { kind: "one_run" } },
  { ...base, policy: { argv: ["echo", "héllo ☃ 😀", "q\"uote\\back\nline\ttab\u0001ctl\u007f "], cwd: "café/src", mode: "background", source_access: "read_only", deadline_ms: 100, writable_profiles: ["cache-1"], network_profile: "registry", credential_profiles: ["TOKEN_A"] }, approval: { kind: "one_run" } },
  { ...base, policy: { argv: ["make"], cwd: "app", mode: "foreground", source_access: "read_write", deadline_ms: 86400000, writable_profiles: ["out"], network_profile: null, credential_profiles: [] }, approval: { kind: "preset", preset_id: "build:main", definition_digest: "a".repeat(64) } },
];
const vectors = requests.map((request) => ({ request, canonical: canonical(request), request_digest: digest(request) }));
writeFileSync(join(__dirname, "remote_command_portable_vectors.json"), JSON.stringify({ project_key_hex: key.toString("hex"), vectors }, null, 1) + "\n");
