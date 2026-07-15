---
status: active
doc_type: guide
audience:
  - end-users
last_verified: 2026-06-11
claims:
  - id: user-guide-apps-mail-source
    type: unit
    claim: The Mail app guide is grounded in Mail app and Proton provider source files.
    file: scripts/tests/test_user_guide_app_docs_claims.py
    assertion: user-guide-apps-mail-source
---

# Mail

> Draft emails and search your Proton mailbox.

## What It Does

The Mail app helps you compose emails and search through your connected Proton Mail inbox. Your mate can draft emails in a format ready to copy or send, and can search your mailbox for specific messages.

**Available skills:**

- **Search** -- Search your Proton Mail inbox by keyword (subject, sender, body text) or list your most recent emails. You can filter by mailbox and control how many results to return (up to 50).

**Email drafting:**

- Ask your mate to write an email and it will create a formatted draft with recipient, subject line, body text, and optional signature. Drafts appear as preview cards you can review before copying or sending.

## How to Use It

- Draft an email: "Write a professional email to my landlord about a broken heater"
- Search your inbox: "Find emails about the invoice from last month"
- List recent emails: "Show me my latest emails"
- Compose with style: "Write a friendly follow-up email to the client about the project update"

## Proton Mail Bridge CLI Connector

You can connect Proton Mail through the OpenMates CLI with:

```bash
openmates connect-account proton
```

This checks whether Proton Mail Bridge is installed. If Bridge is missing, the CLI prints OS-specific install instructions and stops; install Bridge, sign in through Proton Bridge, then run the command again.

When Bridge is installed, the command starts or attaches to Proton Mail Bridge on macOS or Linux and registers a local connector that is online only while the command keeps running. For long-lived use, run the command inside `screen`, `tmux`, or `zellij`.

By default the connector is read-only for Mail search. To allow sending through local Bridge, run:

```bash
openmates connect-account proton --write
```

Write mode requires an explicit confirmation. Sends are queued for a fixed 30-second undo window before SMTP delivery; after delivery OpenMates cannot recall the email. OpenMates never asks for your Proton account password, and Bridge IMAP/SMTP credentials stay local to the CLI connector process.

OpenMates cloud does not connect to Proton directly. The backend sends a request to your running CLI connector, and the CLI talks to Proton Bridge on `localhost` using standard IMAP for reading/search and SMTP for sending.

## Screenshots

![Email draft preview](../../images/user-guide/apps/mail/previews/email/finished.jpg)

![Inbox search results](../../images/user-guide/apps/mail/previews/search/finished.jpg)

## Memories

- **Writing Styles** -- Save different email writing styles for different situations (for example, formal business, friendly follow-up, customer service). Each style can include the tone, level of detail, and a custom signature.

## Tips

- Email drafts are plain text for maximum compatibility with all email programs.
- Your mate applies your saved writing styles automatically when they match the situation.
- Mailbox search requires a connected Proton Mail account. Your email content is protected against security threats before being processed.
- Proton Bridge access from the CLI is online-only. If the connector command stops, Mail search/send requests show the account as offline until you start it again.
- All images in emails viewed through the app are loaded through a privacy-protecting proxy.

## Related

- [Docs](./docs.md) -- Create longer formatted documents
- [Reminder](./reminder.md) -- Set a reminder to follow up on an email
