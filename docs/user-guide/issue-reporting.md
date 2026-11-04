---
status: active
doc_type: guide
audience:
  - users
last_verified: 2026-11-02
claims:
  - id: user-guide-issue-reporting-source
    type: unit
    claim: Issue reporting guidance is grounded in the report issue settings component.
    file: scripts/tests/test_user_guide_product_docs_claims.py
    assertion: user-guide-issue-reporting-source
---

# Issue Reporting

> Report bugs or problems directly from the app. You do not need an account to submit an issue.

## What It Does

If something is not working correctly, you can report it through OpenMates. Your report is sent to the team for investigation. Both logged-in and non-logged-in users can submit issues.

## How to Report an Issue

1. Open the **issue reporting** form (available from the settings or help menu).
2. Describe **what happened**, what went wrong, and any extra context in the single text field.
3. Optionally use the small icon buttons under the field (hover for a tooltip):
   - **Upload screenshot** (signed-in users) -- attach a screenshot or photo.
   - **Select UI element** -- tap the part of the screen that looks broken so its structure is included.
   - **Record voice** -- describe the problem out loud; the transcript is added to the field so you can edit it.
     Voice recording for reports is free, limited to 2 minutes per recording and, for signed-in users, 30 minutes per day.
     Once today's limit is used up, the button is greyed out until tomorrow.
4. If you are not signed in, you can optionally leave an email address so the team can follow up.
5. Submit the report.

If you are in a chat when you report, that chat is included with the report (the form shows a notice) so the team can see what went wrong.

Your browser and device information are included automatically to help with troubleshooting.

## What Happens After You Report

- Your report is **sent by email** to the admin.
- A record is stored securely with sensitive details (email, location, device info) encrypted.
- Console logs from your browser may be included to help diagnose the problem.
- The team investigates and, if you are signed in or left an email address, may follow up by email with questions or a fix.

## Privacy

- Sensitive fields (email, device info, location) are encrypted at rest.
- If you report from inside a chat, an encrypted link to that chat and its latest messages are attached so the team can debug it. Chat text is removed from attached console logs.
- You can report without an account; guest reports include a contact email only if you enter one.

## Tips

- Include as much detail as possible -- "it broke" is harder to fix than "clicking the send button in a new chat shows an error."
- If the problem is visible on screen, describe what you see.
- For sync issues, mention which devices are affected.
- Check [Debug Tools](debug-tools.md) for self-service troubleshooting before reporting.

## Related

- [Debug Tools](debug-tools.md) -- Browser debugging commands
- [Chats](chats.md) -- Chat management
