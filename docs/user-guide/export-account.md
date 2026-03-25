---
status: active
last_verified: 2026-03-24
---

# Export Your Data

> Download all your personal data in a single ZIP file. This fulfils your right to data portability under privacy regulations.

## What It Does

You can export everything OpenMates knows about you -- chats, messages, usage history, invoices, settings, and memories -- as a downloadable ZIP archive. The export is processed entirely on your device, so your data is never stored unencrypted on the server.

## How to Export

1. Go to **Settings > Account > Export My Data**.
2. Verify your identity with your passkey or two-factor authentication code.
3. Wait for the export to complete. A progress bar shows which step is running.
4. Your browser downloads the ZIP file automatically.

### What the Progress Steps Mean

| Step | What happens |
|------|-------------|
| Initialising | Preparing the export |
| Preparing | Gathering a list of all your data from the server |
| Syncing chats | Making sure all chats are available on this device |
| Loading data | Reading your chats and messages |
| Decrypting | Decrypting your data on your device |
| Downloading invoices | Fetching your invoice PDF files |
| Downloading files | Fetching your uploaded files |
| Creating archive | Building the ZIP file |
| Complete | Ready to download |

## What Is Included

Your export ZIP contains:

| Folder / File | Contents |
|--------------|----------|
| `profile.yml` | Your account info (username, email, preferences, credit balance) |
| `compliance_logs.yml` | Your consent history (privacy policy, terms of service) |
| `chats/` | One folder per chat, each with a structured file and a readable markdown version |
| `usage/usage_history.yml` | All your usage records (credits, models, tokens) |
| `payments/invoices.yml` | Invoice history |
| `payments/invoice_pdfs/` | PDF copies of every invoice |
| `settings/app_settings.yml` | Your app-specific settings |
| `settings/memories.yml` | Your saved memories across apps |
| `metadata.yml` | Export statistics and file checksums |
| `README.md` | Description of the archive format |

## What Is Not Included

For security reasons, the following are excluded:

- Encryption keys (master key, chat keys, device keys)
- Actual values of any secret credentials
- Password hashes
- Internal system identifiers

## Tips

- The export runs entirely in your browser. Large accounts with many chats may take a few minutes.
- You can export as often as you like, free of charge.
- If some chats fail to decrypt during export, they are skipped and a note is included. The rest of your data still exports normally.
- Re-authentication is required each time to protect against unauthorised access.

## Related

- [Usage & Billing](usage-and-billing.md) -- Viewing usage details
- [Pricing](pricing.md) -- How credits work
