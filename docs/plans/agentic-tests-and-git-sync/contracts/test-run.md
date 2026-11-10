# Test-run contract (package T1)

Source of truth in code: `backend/shared/python_schemas/code_test_run.py`
(schemas), `backend/shared/providers/e2b_test_runner.py` (E2B executor),
`backend/apps/code/test_run_target.py` (default target). Assertions:
`code-run.tests.project-snapshot`, `code-run.tests.recorded-evidence`.

## Request: `test_run` on the Code Run skill (`TestRunSpec`)

| field | meaning |
| --- | --- |
| `kind` | `unit` \| `browser` \| `cli` |
| `target` | optional `e2b` \| `remote_source`. Default: `remote_source` when the active Project focus has a connected (not offline/revoked) source granting `run_command`, else `e2b`. An explicit value always wins. |
| `project_id`, `source_id` | required for `remote_source` (filled from focus when defaulted) |
| `files` (skill field, E2B) | the Project snapshot contents for this run only; no Project or chat keys reach the sandbox |
| `revisions[]` | `{path, revision}` for exactly the files supplied; the runner rejects a mismatch with `files`. Echoed in the result. |
| `setup_commands[]` | ordered `{argv, cwd=".", timeout_seconds=300}`; stop at the first failure (status `error`) |
| `server` | optional `{command, ready_url, ready_timeout_seconds=60}`; started detached, polled with curl until `ready_url` (`http://localhost|127.0.0.1[:port]/...` only) answers; torn down with the sandbox. Not allowed for `unit`. |
| `test_command` | `{argv, cwd, timeout_seconds}` |
| `preview_step` | optional step name a recorder marks as the preview frame |
| `enable_internet` | default true |

Commands are argv lists (no composed shell strings); use `["bash","-lc","..."]` to opt in to a shell.
Remote runs currently accept only `test_command` (no setup/server) until lane T6.

## Result: `TestRunResult` (same for all kinds and targets)

Delivered on the execution status payload and the assistant completion result as `test_result`.

- `kind`, `target`, `status` (`passed|failed|error|cancelled|timed_out`), `exit_code`, `duration_ms`
- `revisions[]`: revisions the run used. A result whose set differs from the current files is stale: `result_is_current()`.
- `passed`, `failed`, `skipped`, `tests[]` (`{name, status, duration_ms, error}`)
- `steps[]` ordered: `{name, start_ms, end_ms, status passed|failed|skipped, error, is_preview, command, output}`; offsets are ms from run start (after upload). The runner adds one step per setup command, `Starting server`, `Waiting for server`, `Running tests`; recorder steps follow, so recorder offsets are relative to the start of the test command's own timeline and `preview_step_index` indexes the merged list.
- `evidence[]`: `{kind video|terminal_cast|preview_frame|trace|report, path, mime_type, size_bytes, asset_id, at_step}`. `asset_id` is the persisted encrypted artifact id (set after storage).
- `preview_step_index`, `error`.

Status rules: error if setup/server fails, the report is malformed, or a non-unit run wrote no report; failed if exit code != 0 or any test failed; timed_out on exit code 124. `unit` needs no report: without one, status comes from the exit code and `tests` is empty.

## What a recorder must write (T2 browser, T3 cli)

All files go under `outputs/test-run/` relative to the workspace root (E2B: `/home/user/openmates-run`; remote: the worktree). Every test command receives env `OPENMATES_TEST_RUN_DIR=outputs/test-run` and `OPENMATES_TEST_RUN_KIND=<kind>`.

| file | kind | content | max bytes |
| --- | --- | --- | --- |
| `report.json` (required for browser/cli) | report | `{"tests":[...], "steps":[...], "preview_step_index": int?}` shaped as `TestCaseResult` / `TestStep`; `is_preview: true` on one step is equivalent to `preview_step_index` | 1 MB |
| `video.webm` | video | browser recording | 15 MB |
| `trace.zip` | trace | Playwright trace | 8 MB |
| `preview.png` | preview_frame | the frame at the preview step, else last non-blank frame before the final assertion | 2 MB |
| `terminal.cast` | terminal_cast | asciicast of the cli run | 2 MB |

For `cli`, each step sets `command` (entered) and `output` (produced, <= 4000 chars); no video needed.
Files over the cap are skipped with reason `file_too_large`; at most 12 artifacts and 40 MB total per test run (normal runs keep 10 / 5 MB / 20 MB and do not allow `.webm/.mp4/.cast`). `.mp4` is also accepted from `outputs/` in test runs (15 MB).
Evidence is found by exact filename in `RECORDER_FILES`; anything else in `outputs/` follows the normal artifact rules.

Runner hook: `run_tests_in_e2b(files, spec, on_output, api_key, should_cancel, recorder_wrapper)`. `recorder_wrapper(spec)` returns the argv that replaces `test_command.argv` (e.g. `["python","/opt/openmates/record_browser.py","--", *argv]`). Browser runs use `E2B_APPLICATION_PREVIEW_TEMPLATE` (Playwright preinstalled, `PLAYWRIGHT_BROWSERS_PATH` set) when configured. T2/T3 must supply the wrapper from their modules and wire it in `execute_test_run` (`backend/apps/code/tasks/test_run_execution.py`) by kind; until then browser/cli runs without a recorder yield `error` (no report).

## Consumers

- T4 (embed): read `final_status["test_result"]` (and the `test_result` key of the completion result); persist it in the encrypted embed content; resolve evidence through `asset_id`.
- T6 (remote): produce the same `TestRunResult` with `target="remote_source"` and upload evidence as artifacts of the run.

## CLI recorder and step convention (package T3)

`kind == "cli"` runs wrap the test command with `cli_recorder_wrapper`
(`backend/shared/providers/e2b_cli_test_recorder.py`). The recorder program
`backend/shared/providers/terminal_test_recorder.py` (Python standard library only) travels inside the
argv as a `python3 -c` source argument, so nothing is baked into the E2B template and the same argv works
on a remote worktree. It runs the command under a pseudo-terminal (100x30) and writes `terminal.cast`
(asciicast v2, output events only) and `report.json` into `OPENMATES_TEST_RUN_DIR` (found by walking up
from the cwd, so tests in subdirectories work). The recorder exits with the command's exit code (124 after
SIGTERM from the timeout, 127 if the program cannot start).

Step markers a test script emits (OSC 777, invisible on replay):

```
printf '\033]777;openmates-step;%s\007' "recipes add Pancakes"   # starts a step; text = command entered
printf '\033]777;openmates-step-end;%s\007' "$?"                  # optional: ends it with an exit code
```

`ESC \` may replace `BEL`. Rules: a step ends at the next start marker or at process end; its status is
`failed` if its step-end code is non-zero, else for the last step the process exit code decides, earlier
steps without a step-end marker count as passed. An unreadable step-end code is a failed step. Without any
marker the run is one step whose `command` is the test command and whose `output` is the whole output
(no prompt detection: it is not reliable). `spec.preview_step` marks the step whose command equals it.
`report.json` has one test (the test command, failed when the exit code or any step failed).

Fidelity and caps: markers stay in the cast; in a step `output` only markers are removed and CRLF becomes
LF. Step `output` is cut to 4000 chars ending `[openmates: step output truncated, N more characters]`, the
command to 1000, the name to 300; more than 500 steps append further output to the last step with a
visible note. The cast stops at 2 MB with a final event `[openmates: terminal cast truncated, 2 MB limit
reached]` while the command keeps running; the report is shrunk (output first) to stay under 1 MB.
Truncation never fails the run.

## Browser recorder details (T2, refinement)

Code: `backend/shared/providers/e2b_test_recorder.py` (host wrapper) and `backend/shared/providers/test_recorder_assets/` (`record_browser.py`, `reporter.cjs`, uploaded at run time inside the wrapper argv; no template rebuild).

- The test command must invoke `playwright test` (directly in argv or inside a `bash -lc` string); the recorder injects an overlay config (video on, trace retain-on-failure, screenshot on, 1 worker, custom reporter) beside the user's config. Other commands run unrecorded and, being browser runs, end as `error` (no report).
- Preview marker: a `test.step` titled `[preview] <name>` (prefix stripped), or the `preview_step` input matching a `test.step` title (input wins). The frame is taken at the end of that step. Otherwise: last frame before the final `expect` step whose 64x36 gray standard deviation is >= 2.0 (sampled every 250 ms backwards), else the frame just before the assertion. Without ffmpeg the last end-of-test screenshot is used.
- `report.json` additionally carries `notes[]` (ignored by the parser): `file_too_large`, `video_reencoded`, `video_partial`, `steps_truncated`, preview reason. Notes are also printed with prefix `[openmates-recorder]`.
- Step offsets are on the video timeline (multi-test runs are concatenated; a test's offset is the summed length of earlier videos). Steps kept: `test.step`, `expect`, `pw:api`.
- Needs `ffmpeg` (system, else the bundled one) for concat, frame extraction and re-encode; the preview template currently has only the bundled one.
