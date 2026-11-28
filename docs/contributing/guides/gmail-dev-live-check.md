# Five-minute Gmail check on dev

Use the dedicated Google test account and a synthetic email already in its inbox. For
example, use a thread titled “OpenMates Gmail smoke test” with the body “The
test meeting is at noon.” Keep the Gmail inbox, Drafts and Sent folders available
in a second tab so you can compare them.

1. **Connect.** On OpenMates dev, open **Settings → Account → Connected accounts**.
   Open the test account’s existing Google row and choose **Add Gmail access**.
   If the account is new, choose **Add account → Google** and enable Gmail.
   Grant read and draft access. Check that Settings shows the correct email
   on one Google row and lists the Calendar and Gmail permissions there if
   Calendar access was already granted.
2. **Search.** In a new dev chat ask “Search my connected Gmail for the
   subject OpenMates Gmail smoke test.” Check that the result matches the test
   message and account.
3. **Read.** Ask “Read that Gmail thread and tell me the meeting time.” Check
   the answer against the synthetic message.
4. **Draft.** Ask “Create an unsent Gmail reply draft in that thread with the
   body ‘Thanks, noon works for me.’” Check the subject and recipients in the
   approval prompt before approving. In Gmail, confirm one new draft with
   the expected text and confirm Sent has no new message.
5. **Report.** Share whether connect, search, read and draft each passed. If
   a step fails, capture the error text or a screenshot with only test data.
   Discard the synthetic draft when finished.
