---
status: active
doc_type: reference
audience:
  - end-users
  - technical-users
last_verified: 2026-06-11
claims:
  - id: cli-authentication-uses-pair-login-command
    type: unit
    claim: CLI authentication is represented as a pair-login command surface, not a password-prompt flow.
    source:
      - frontend/packages/openmates-cli/src/cli.ts
      - frontend/packages/openmates-cli/src/client.ts
      - frontend/packages/openmates-cli/src/storage.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-authentication-uses-pair-login-command
    verified: '2026-06-11'
  - id: cli-authentication-docs-cover-login-and-signup
    type: unit
    claim: CLI authentication docs cover pair-login and terminal signup without documenting password flags.
    source:
      - frontend/packages/openmates-cli/src/cli.ts
      - frontend/packages/openmates-cli/src/client.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-authentication-docs-cover-login-and-signup
    verified: '2026-06-11'
---

# Authentication

The OpenMates CLI uses pair-auth for login -- it never asks for your account password during login. Authentication is completed by confirming a pair PIN in the web app or scanning a QR code. New accounts can also be created with the guided `openmates signup` flow, which collects passwords and recovery secrets through hidden terminal prompts instead of command-line flags.

## Login

```
openmates login
```

This initiates the pair-auth flow:

1. The CLI generates a pairing token and displays a QR code (or pair PIN) in the terminal.
2. Open the OpenMates web app and go to Settings > Developers > Devices.
3. Scan the QR code or enter the pair PIN to authorize the CLI session.
4. The CLI receives a session token and stores it locally.

After login, all subsequent commands use the stored session automatically.

## Logout

```
openmates logout
```

Clears the local session token. You will need to run `login` again to use authenticated commands.

## Who Am I

```
openmates whoami
openmates whoami --json
```

Displays your account information (username, email, plan). Use `--json` for machine-readable output.

## Signup

```
openmates signup --email you@example.com --username your_name --invite-code <code>
openmates signup --backup-codes-output ./backup-codes.txt --recovery-key-output ./recovery-key.txt
```

Signup creates a password account from the terminal using the same client-side encrypted signup crypto as the web app. Passwords, 2FA verification codes, backup codes, and recovery keys are handled through hidden prompts or owner-only files; the CLI rejects password-style command-line flags so secrets do not land in shell history.

| Option | Description |
|--------|-------------|
| `--email <email>` | Email address; prompted when omitted |
| `--username <name>` | Username; prompted when omitted |
| `--invite-code <code>` | Invite code when required |
| `--gift-card-code <code>` | Redeem a gift card after account creation |
| `--backup-codes-output <path>` | Save backup codes to a `0600` file |
| `--recovery-key-output <path>` | Save recovery key to a `0600` file |
| `--skip-2fa` | Explicitly skip 2FA setup after warning |
| `--skip-recovery-key` | Explicitly skip recovery-key setup after warning |
| `--yes` | Confirm warning prompts |
| `--json` | Output a non-secret JSON summary |

## Session Storage

Session data is stored in `~/.openmates/session.json`. This file contains your session token and is used for all authenticated API requests.

## Security

- **File permissions:** All files in `~/.openmates/` are created with `0o600` (owner read/write only). The directory itself is `0o700` (owner only).
- **No credentials stored:** The CLI never stores your password or passkey. Login persists only the session token from pair-auth; signup stores only the normal encrypted account/session material needed for later CLI use.
- **Pair-auth login:** Login requires explicit approval in the web app, which keeps normal account-password authentication out of the CLI login path.
- **Blocked operations:** Security-sensitive actions (passkey management, password changes, 2FA changes, device sessions) are blocked in the CLI and must be performed in the web app. Guided signup and missing-method setup are dedicated CLI flows, not raw settings passthrough. See [settings.md](./settings.md) for the full list.

## Key Files

- See [cli.ts](../../../frontend/packages/openmates-cli/src/cli.ts) for the `login`, `logout`, and `whoami` command handlers
- See [client.ts](../../../frontend/packages/openmates-cli/src/client.ts) for `loginWithPairAuth()` and session management
- See [storage.ts](../../../frontend/packages/openmates-cli/src/storage.ts) for session file persistence and permission handling

## Related Docs

- [README](./README.md) -- CLI overview and installation
- [Settings](./settings.md) -- blocked security paths
- [CLI Standards](../../contributing/standards/cli.md) -- storage permission rules (Rule 8)
- [Signup & Auth Architecture](../../architecture/core/signup-and-auth.md) -- pair-auth protocol details
