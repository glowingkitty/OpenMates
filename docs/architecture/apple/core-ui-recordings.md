# Core Apple UI test recordings

Successful core relevant Apple E2E tests must retain playable video for user review.
The `OpenMates_Core_UI_Evidence` scheme uses `apple/OpenMatesCoreUI.xctestplan`.
It selects account-free guest/interests, offline-capability controls, and model
transfer/verification tests. Extend the selected core cases as approved Watch,
storage, and offline-send work becomes executable; do not select the whole suite.

## Capture and delivery

1. Follow the iOS skill, session/native-job ownership and capacity guards. Build
   source-matched Debug Simulator test products without replacing installed apps
   or clearing account data. Record the actual source manifest and app version/build.
2. Run the focused scheme/test plan. It sets `uiTestingScreenshotsLifetime` and
   `userAttachmentLifetime` to `keepAlways`, and `preferredScreenCaptureFormat`
   to `screenRecording`. These correspond to Xcode's Automatic Screen Capture
   **On, and keep all** and preferred **Video** settings.
3. Preserve the original `.xcresult` and exact test summary. Export attachments
   with the active Xcode's `xcrun xcresulttool export attachments --path <result>
   --output-path <owned-output>`. Do not use `--only-failures`.
4. Check that every selected successful test has a usable, nonempty recording;
   inspect its duration and representative frames. Bind each exported clip to
   the test/result, source manifest, app version/build and target. A pass alone
   does not establish complete visual parity or real-service/device behavior.
5. Show the playable video attachments in the final Codex response. Keep personal
   account content private. Retain available failure/retry clips and clearly label
   fixture evidence. A missing video remains a visual-proof gap; retry export or
   upload from retained results without rerunning an otherwise passing test.

Apple documents successful-run video retention in
[Record, replay, and review: UI automation with Xcode](https://developer.apple.com/videos/play/wwdc2025/344/?time=1146).
