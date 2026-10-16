# Enhanced personal data anonymization (offline AI model)

The optional CLI detector supplements deterministic patterns and configured
personal data with OpenAI Privacy Filter Q8. It uses the evaluated native C++
runtime, without GLiNER, Python or PyTorch on the user's machine.

On a supported machine, the signed-in TUI shows one nonblocking installation
offer per OS user/device. `/privacy install` downloads and enables it;
`/privacy later` dismisses it. F6/F7 activate these choices while preserving a composer draft. Scripts, CLI updates and remote-access startup
never offer or download weights automatically.

```text
openmates privacy install
openmates privacy status
openmates privacy disable
openmates privacy enable
openmates privacy enable --documents
openmates privacy enable --project FULL_PROJECT_ID
openmates privacy disable --project FULL_PROJECT_ID
openmates privacy update
openmates privacy remove
```

Explicit scripted installation/removal requires `--yes`. Installation supports
`--download-only` and importing the exact pinned weights with `--model-file`.
Settings in the TUI use `/privacy enable documents` or
`/privacy enable project FULL_PROJECT_ID`; an open Project can supply the ID.

Enabled profiles automatically scan CLI/TUI messages. Document attachment text
and each Project opt in separately. Ordinary source reads, search results and
terminal output keep the deterministic path unless the relevant supported
content boundary has an explicit enhanced setting. This implementation does not
send browser/native user input to a remote machine for model inference.
Binary uploads and server-extracted PDF/image/audio content are outside this
local text detector's coverage.

The initial packaged target is Linux ARM64 with FP16 and dot-product CPU
instructions, at least two cores and 4 GiB RAM; 8 GiB is recommended for coding.
Installation requires 4 GiB free disk for staging and safe updates. Weights are
1,637,572,192 bytes (1.53 GiB), with about 2 GiB active model RAM. Other operating
systems and architectures report unsupported and retain deterministic detection.

One private Unix socket and one serialized native worker serve an OS user.
The model loads on demand, requires at least 2.5 GiB available memory, uses at
most four CPU threads and unloads after two idle minutes. A 3 GiB native RSS
limit stops excessive allocation. Model inference is denied socket syscalls;
the Node installer alone can download the pinned weights after explicit action.
The native process receives no account credentials. Runtime assets and weights
are checked against their pinned checksums.

Messages and selected files are processed in overlapping windows with progress,
without silent truncation or a size-based downgrade. The bounded in-memory
cache holds only detection ranges, keyed by profile and content digest. Failed
or unavailable selected scans block that send, with retry/disable guidance.
Disabling the enhancement retains deterministic protection.

Native byte offsets are validated and translated into JavaScript string
positions. Coding UUIDs, hashes and existing tokens have structural guards.
Deterministic matches take precedence without losing the uncovered part of a
broader model match. Original values stay in the existing encrypted client-owned
maps; line endings and exact local file restoration are preserved. Project
focus, write policy and conflict checks retain their existing authority.

The model is probabilistic and primarily evaluated in English. It does not
guarantee complete detection; configured values and deterministic secret
patterns remain useful. See the [offline evaluation](offline-pii-evaluation-2026-10-03.md).

Verification: 22 focused mapping/scope/output/attachment checks, native network-denial self-test,
and a real offline scan using isolated CLI state and a disposable README.
The real scan detected the synthetic name, address and email, preserved exact
CRLF restoration, and honored document/Project opt-ins. Cold scan plus model
verification/loading took about 3.3 seconds on the measured dev host.
The isolated CI lifecycle case passed in run 37119460496 and performs no real model inference.

Permanent privacy assertions: `feature.pii-protection@1`, particularly
`pii.surface.semantic-parity` and `pii.message.owner-local-reveal`.
Implementation decisions and publication evidence remain in
`docs/plans/native-agentic-coding-readiness/plan.yml` (TASK-4569).
