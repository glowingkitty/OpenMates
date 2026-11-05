# Encrypted Project creation compatibility

`protocol.project-create.v1` uses `fixtures/project-create.json` with actual
npm/Python/Rust API-key SDK clients and one canonical synthetic loopback HTTP
peer, `project_create_server.py`. It verifies direct library requests and locally
decrypts the actual posted payload. No OpenMates CLI, account, inference or
product endpoint is involved. Test helpers may run as fixture-service processes;
SDK runtime never starts them.

The existing npm/Python public create inputs have no write-policy parameter.
Their compatible default is now `write_mode="always_ask"`, which requires approval
for future file changes. Both preserve their public signatures and existing
name/description/icon/color/pinned/context defaults. Each call creates a new
Project key and default focus UUID, and encrypts exactly `{default_focus}` under
the Project key, using the canonical CLI's generated focus text. Neither plaintext
settings nor focus instructions are posted. The Rust API already exposes an
explicit write policy; this semantic request fixture passes `AlwaysAsk` explicitly
and does not change that API's policy requirement.

Three shared vectors cover repeated Personal creation, repeated Team creation,
and missing-name rejection without a create POST. The peer checks:

- Backend-required `write_mode`, `default_focus_id`, `encrypted_settings` and
  existing identity/timestamp fields are present with valid values.
- The Project key, focus UUID and Project UUID differ on repeated creates.
- Personal keys wrap under the account key; Team keys have exactly one matching
  Team/epoch wrapper and no account-key wrapper.
- Names, descriptions, icons, colors, slugs and canonical default-focus settings
  decrypt to the expected values. Slug lookup hashes match the scope's lookup key.
- Headers carry the expected SDK identity and bearer portion only. The setup
  suffix, master/Project keys and private title/description remain off the wire.
- Public return values reflect the decrypted response without changing call shape.

The fixture's public master wrapper uses independently computed
PBKDF2-SHA256/100000 plus raw AES-GCM. The setup suffix stays local while the SDK
opens that wrapper. Project key/ciphertext/focus generation happens in the actual
SDK being tested, rather than in the mock or adapter.

Run from the workspace:

```sh
node tests/sdk-conformance/runners/project-create.mjs --fixture tests/sdk-conformance/fixtures/project-create.json --capability protocol.project-create.v1
python3 tests/sdk-conformance/runners/project-create.py --fixture tests/sdk-conformance/fixtures/project-create.json --capability protocol.project-create.v1
cargo run --example project-create-conformance --manifest-path packages/openmates-rust/Cargo.toml --locked --quiet -- --fixture tests/sdk-conformance/fixtures/project-create.json --capability protocol.project-create.v1
```

`OPENMATES_SDK_CONFORMANCE_PYTHON` optionally supplies an absolute interpreter for
Rust/npm fixture-service startup. The conformance gate uses its own interpreter.
Each runner returns the exact fixture SHA256 and all exercised vector IDs.

This proves the encrypted create request and compatible SDK defaults. It does not
establish complete Project API parity, backend enforcement, source/file work,
settings mutation, import/export, grants or focus activation. Those remain separate
capabilities in the broader parity inventory.
