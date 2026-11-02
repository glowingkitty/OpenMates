# Engineering Tasks: dev-server CLI login

The dev server uses the globally installed `openmates` package with its personal
dev-testing account. The engineering Project is `OpenMates`
(`96033196-e4b1-431e-b773-ba221e952fed`). Do not create another Project or
replace that CLI login for signup tests; use a separate `OPENMATES_STATE_DIR`
for signup. When the foreground CLI is used, it runs in the `openmates-remote`
Zellij session and must be restarted deliberately after a host reboot.

## Recover the global dev login (`Not logged in`)

An expired global session is a one-time operator recovery, not a reason to add
login to a hook or every CLI invocation. First try the normal pair-auth flow:

```sh
openmates --api-url https://api.dev.openmates.org login
```

Approve the displayed pair request while signed in to the personal DEV TEST
account. Do not approve it from a numbered E2E/signup account. If browser pairing
is unavailable on the dev host, the repository's owner-only `.env` contains the
same account under `OPENMATES_PERSONAL_TEST_ACOUNT_EMAIL`, `_PASSWORD`, and
`_OTP_KEY` (the `ACOUNT` spelling is retained for compatibility). The audited
`scripts/openmates_cli_test_account.mjs` helper can restore the normal global
session without printing those values. Map only those three keys in process;
never source or print the whole `.env`, and never substitute the generic
`OPENMATES_TEST_ACCOUNT_*` or numbered account keys:

```sh
node - <<'NODE'
const fs = require('fs');
const { spawnSync } = require('child_process');

const values = {};
for (const raw of fs.readFileSync('.env', 'utf8').split(/\r?\n/)) {
  const line = raw.trim();
  if (!line || line.startsWith('#') || !line.includes('=')) continue;
  const separator = line.indexOf('=');
  const key = line.slice(0, separator).trim();
  let value = line.slice(separator + 1).trim();
  if ((value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
  values[key] = value;
}

const environment = { ...process.env };
for (const suffix of ['EMAIL', 'PASSWORD', 'OTP_KEY']) {
  const source = `OPENMATES_PERSONAL_TEST_ACOUNT_${suffix}`;
  if (!values[source]) throw new Error(`Missing ${source}`);
  environment[`OPENMATES_TEST_ACCOUNT_PERSONAL_${suffix}`] = values[source];
}
const result = spawnSync(process.execPath, [
  'scripts/openmates_cli_test_account.mjs', 'login', '--slot', 'PERSONAL',
  '--api-url', 'https://api.dev.openmates.org'
], { env: environment, stdio: 'inherit' });
process.exit(result.status ?? 1);
NODE
```

Fail closed if the account or Project does not match. The expected safe identity
is API `https://api.dev.openmates.org`, username `Glowingkitty`, user ID
`f21b15a5-a36a-4596-b014-0941b6882e96`, account ID `1BV756R`, and Project
`96033196-e4b1-431e-b773-ba221e952fed`. Verify read access before any Task
mutation:

```sh
openmates whoami --json
openmates tasks list --project 96033196-e4b1-431e-b773-ba221e952fed --json
```

`Project not found` means the wrong account was selected. Stop and restore the
personal account; do not create a replacement Project or migrate cached Tasks.

## Efficient commands and activity

Write Tasks through the installed global CLI. Use the short ID and ordinary
terminal output for a human acknowledgement, for example:

```bash
openmates tasks activity add TASK-7947 --message 'Project migration finished; all 26 Tasks retained their owners.'
```

Use `--json` when a caller needs to parse fields. A pending delivery is not
success: retain its ID and let the foreground transport retry. Do not pipe away
errors or hide delivery state, and do not fetch after an acknowledged write just
to repeat its result. Activity states the changed outcome or blocker in one or
two sentences; keep detailed evidence in a linked file or receipt.
