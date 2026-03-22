# Authentication

The OpenMates CLI uses pair-auth for login -- it never asks for your email or password. Authentication is completed by confirming a pair PIN in the web app or scanning a QR code.

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

## Session Storage

Session data is stored in `~/.openmates/session.json`. This file contains your session token and is used for all authenticated API requests.

## Security

- **File permissions:** All files in `~/.openmates/` are created with `0o600` (owner read/write only). The directory itself is `0o700` (owner only).
- **No credentials stored:** The CLI never stores your email, password, or passkey. Only the session token from pair-auth is persisted.
- **Pair-auth only:** This design ensures that the CLI cannot be used for credential phishing. Authentication always requires explicit approval in the web app.
- **Blocked operations:** Security-sensitive actions (passkey management, password setup, 2FA configuration, device sessions) are blocked in the CLI and must be performed in the web app. See [settings.md](./settings.md) for the full list.

## Key Files

- See [cli.ts](../../frontend/packages/openmates-cli/src/cli.ts) for the `login`, `logout`, and `whoami` command handlers
- See [client.ts](../../frontend/packages/openmates-cli/src/client.ts) for `loginWithPairAuth()` and session management
- See [storage.ts](../../frontend/packages/openmates-cli/src/storage.ts) for session file persistence and permission handling

## Related Docs

- [README](./README.md) -- CLI overview and installation
- [Settings](./settings.md) -- blocked security paths
- [CLI Standards](../claude/cli-standards.md) -- storage permission rules (Rule 8)
- [Signup & Auth Architecture](../architecture/signup-and-auth.md) -- pair-auth protocol details
