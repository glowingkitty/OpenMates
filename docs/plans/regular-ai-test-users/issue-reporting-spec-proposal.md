# Proposed Specification change: several screenshots per report (TASK-7525)

The issue-reporting Specification is approved; this is the proposed wording for
owner approval. Nothing in `specifications/` has been edited.

## specification.yml

`issue-reporting.form.single-text-quick-actions` (`must:`), changed phrase:

- old: "... to upload a screenshot (authenticated users), select a UI element, ..."
- new: "... to attach screenshots (authenticated users; up to five, each shown as
  a removable thumbnail), select a UI element, ..."

`issue-reporting.submission.confirmed-and-durable` (`must:`):

> A successful report submission returns stable full and short issue
> identifiers, visibly confirms the report, and exposes the eventual persistence
> state of the attached screenshots (how many were stored and how many were
> skipped as invalid or larger than 2 MB) and any requested asynchronous debug
> report. A report keeps up to five screenshots; a request with more than five
> is rejected, and every stored screenshot is shown to the admin (email, debug
> report) and deleted with the report.

## examples.yml

New example `several_screenshots` (linked from both assertions):

- Given a signed-in user with the Report Issue form open
- When they attach three screenshots, add a sentence of text and submit
- Then the form confirms the report, the status endpoint reports
  `screenshot_count: 3`, the admin issue detail lists three screenshot URLs, and
  attaching a sixth screenshot in the form is refused with a visible hint.
- Legacy clients that send one `screenshot_png_base64` still work and count as
  the first screenshot.
