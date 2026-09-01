# Subscription-Backed Inference Research

> Status: Research complete; implementation deferred
> Last verified: 2026-08-04
> Scope: OpenAI Codex subscriptions, local inference bridges, and future provider expansion
> Related: `backend/apps/ai/processing/main_processor.py`, `backend/apps/ai/utils/llm_utils.py`, `frontend/packages/openmates-cli/src/remoteAccess.ts`, `docs/plans/cli-remote-access-live-bridge/plan.yml`

## Goal

Investigate whether OpenMates can let users run main-model inference through an
existing AI subscription instead of paying OpenMates credits for that portion of
the request. Preprocessing, postprocessing, hosted skills, storage, and other
OpenMates-owned work would remain chargeable where applicable.

The same research also covers subscription-backed inference for internal
automation such as session summaries, change summaries, and translation scripts.

No implementation is approved by this document. Authentication, billing,
privacy, tool execution, and cross-client behavior require a full executable
spec before product work starts.

## Conclusions

1. ChatGPT plans officially include programmatic Codex use through `codex exec`,
   the Codex SDK, and Codex App Server. Subscription access does not turn into
   general OpenAI API credit; ordinary Responses and Chat Completions API calls
   remain separately billed.
2. Use `codex exec --ephemeral` with GPT-5.6 Luna for bounded local automation
   such as summaries, extraction, classification, and translation.
3. Prefer Codex App Server over `codex exec` for a future interactive OpenMates
   Main Processor integration. App Server supports streaming turns,
   cancellation, usage events, account state, and caller-defined dynamic tools.
4. Prototype hosted App Server first so nontechnical users do not need a local
   CLI process. Keep the runtime transport abstract so the same adapter can later
   run on a user's machine through `openmates remote-access`.
5. Do not assume another provider's subscription can be used because its CLI has
   a headless mode. Anthropic currently requires prior approval before a
   third-party product offers Claude subscription login or routes work through
   consumer subscription credentials.

## Supported OpenAI Surfaces

| Surface | Subscription-backed | Intended use | OpenMates fit |
| --- | --- | --- | --- |
| `codex exec` | Yes, using saved ChatGPT authentication | Scripts, pipelines, summaries, release notes, structured output | Good for one-shot automation; poor for the interactive Main Processor |
| Codex SDK | Yes, using Codex authentication | Programmatic local Codex threads | Useful wrapper around App Server, especially for prototypes |
| Codex App Server | Yes | Embed Codex authentication, threads, streamed events, approvals, and tools into another product | Best future Main Processor candidate |
| OpenAI Responses/Chat Completions API | No | General application inference | Supported through API keys, but billed separately from ChatGPT |
| Codex access token | Business and Enterprise only | Trusted noninteractive Codex automation | Useful for managed organizations, not a consumer login replacement |

The public lightweight model identifier is `gpt-5.6-luna`. OpenAI positions it
for high-volume, well-scoped work including transformation, extraction,
classification, routing, structured summaries, and background automation.

## Internal Automation

For OpenCode hooks, release intelligence, and translation scripts, a shared
one-shot adapter can invoke:

```bash
codex exec \
  --ephemeral \
  --model gpt-5.6-luna \
  --sandbox read-only \
  --output-schema <schema.json> \
  "<bounded instruction>"
```

The adapter should use a dedicated empty working directory, bounded input,
timeouts, explicit schema validation, redaction, and visible failures. It must
not expose subscription tokens or silently switch to API billing.

Relevant Gemini-backed migration seams include:

- `scripts/auto_translate.py`
- `scripts/_ar_translate_batch.py`
- `backend/scripts/translate_text.py`
- `scripts/release_intelligence.py`
- `scripts/audit_example_chat_quality.py`

OpenCode supports `session.idle`, `session.compacted`, `session.diff`, and other
session events. A future summarizer should run as a separate plugin and enqueue
detached, deduplicated work rather than blocking an OpenCode lifecycle hook.
`session.idle` occurs after responses, not only when a user is permanently done
with a chat, so it requires debouncing and content-hash deduplication.

## Hosted App Server Authentication

### User Experience

A hosted implementation can connect a ChatGPT subscription without requiring
the OpenMates CLI:

1. The user opens the provider settings and selects **Connect ChatGPT subscription**.
2. OpenMates starts an isolated Codex App Server authentication context.
3. OpenMates calls `account/login/start` with `type: "chatgptDeviceCode"`.
4. App Server returns a verification URL, one-time user code, and login ID.
5. OpenMates opens or displays `https://auth.openai.com/codex/device` and shows the code.
6. The user signs into ChatGPT and enters the code.
7. App Server polls OpenAI, persists the resulting credentials, and emits
   `account/login/completed` followed by `account/updated`.
8. OpenMates displays the account plan and current connection state.

Device-code login is currently beta. It must be enabled in the user's ChatGPT
security settings or permitted by their workspace administrator.

### Why Not Browser Callback Login

The standard ChatGPT browser flow generated by App Server redirects to:

```text
http://localhost:<port>/auth/callback
```

For a remotely hosted App Server, `localhost` in the user's browser refers to
the user's device, not OpenMates infrastructure. App Server does not currently
accept a custom public callback URL in `account/login/start`. Device-code login
therefore provides the practical hosted flow without tunneling or a local
helper.

### Credential Isolation

Codex resolves one `CODEX_HOME` and one active account when App Server starts.
Authentication is process-global, not scoped to a thread or JSON-RPC
connection. A multi-user OpenMates deployment must therefore use a distinct
credential and runtime boundary per user.

The proposed hosted shape is:

```text
one encrypted persistent CODEX_HOME per user
one App Server process per active user
stdio transport between OpenMates and App Server
on-demand startup and idle shutdown
container/process filesystem and network isolation
```

Codex can store access, ID, and refresh tokens in `$CODEX_HOME/auth.json` or an
OS credential store. Hosted containers will generally require file-backed
storage, so OpenMates would become custodian of account-equivalent refresh
tokens. They must be encrypted at rest, excluded from logs and backups where
possible, owner-scoped, revocable, and deleted on disconnect/account deletion.

Using local stdio avoids App Server's experimental remote WebSocket transport.
The user never connects directly to the App Server process.

## Tool Calling Compatibility

App Server's experimental `dynamicTools` facility maps closely to OpenMates'
existing generated function schemas. OpenMates can attach caller-defined names,
descriptions, and JSON input schemas to a thread. When Codex selects a tool, App
Server issues an `item/tool/call` JSON-RPC request and waits for the embedding
client to return structured content and success state.

This is preferable to initially exposing OpenMates skills as MCP tools because
OpenMates must remain authoritative for:

- Skill allowlisting and user intent.
- Permission and action confirmation.
- Connected-account token scoping.
- Cancellation, timeout, and retry behavior.
- Billing and usage attribution.
- PII placeholder restoration and result sanitization.
- Embed creation, deduplication, and encrypted chat behavior.

### Main Processor Impedance Mismatch

The current provider contract expects a provider stream to finish with one or
more completed tool calls. Main Processor then executes those tools and starts
another provider request with assistant tool-call history and tool-result
messages.

App Server instead pauses the same active turn while waiting for each dynamic
tool result:

```text
Codex starts turn
Codex requests dynamic tool
App Server waits
OpenMates executes the existing skill
OpenMates returns the result
Codex continues the same turn
```

A naive `invoke_codex_chat_completions` adapter would deadlock because Main
Processor waits for the provider stream to finish while App Server waits for the
tool result. A future implementation needs a dedicated Codex turn driver that
reuses existing skill execution and policy services rather than treating App
Server as an ordinary stateless provider.

Dynamic tools are experimental. The integration must pin a Codex runtime,
generate version-matched protocol schemas, and maintain contract tests for
login, streamed text, multiple tool calls, errors, cancellation, token usage,
rate limits, and process restart.

## Runtime Security

A hosted coding-agent process must not receive incidental access to OpenMates
infrastructure. The future runtime must:

- Start in an empty disposable working directory.
- Mount no user repository, application source, secrets, or Docker socket.
- Disable model-facing shell access.
- Disable execution environments and edit tools where supported.
- Load no user Codex configuration, plugins, skills, memories, or arbitrary MCP servers.
- Allow only OpenMates-provided dynamic tools.
- Filter host-operation RPCs such as process spawn, command execution,
  unsandboxed shell commands, and filesystem mutation.
- Restrict process-level filesystem and network access independently of model settings.
- Bind every request to the authenticated owner, device, chat, message, and expiry.

Model-facing configuration is not a sufficient security boundary. Container or
process isolation and a JSON-RPC method allowlist remain mandatory.

## Future Local Provider Bridge

The hosted adapter should not preclude a local runtime. A later revision of
`openmates remote-access` can supervise local inference providers while it is
running. The v1 remote-access specification deliberately excluded process
execution and model workers; those exclusions describe v1, not the intended
permanent product scope.

On interactive CLI launch and whenever remote access starts, OpenMates can
detect supported local tools and suggest `openmates provider connect`:

```text
Local inference

Codex       installed, ChatGPT subscription connected
Claude Code installed, subscription routing unavailable without provider approval
Ollama      installed, 3 models available

Run `openmates provider connect` to configure a provider.
```

Discovery output must not appear when stdout is not a TTY, under `--json`, or
after the user has dismissed/configured the notice. Once configured, starting
`openmates remote-access` should be sufficient to make local providers
available; a second foreground worker command is not desirable.

The same App Server adapter can support both locations:

```text
CodexAppServerAdapter
  HostedStdioTransport
  RemoteAccessTransport
```

The local path keeps provider credentials on the user's machine and naturally
isolates one Codex account. Its tradeoffs are device availability, additional
network latency, local queueing, and loss of provider access when the foreground
bridge disconnects.

## Provider Policy Boundaries

Provider support must distinguish technical capability from permission to use
subscription credentials in a third-party product.

| Provider path | Current conclusion |
| --- | --- |
| OpenAI Codex App Server/SDK with ChatGPT authentication | Officially supports product embedding and programmatic authentication; prototype is justified. Confirm intended general-purpose commercial workload before public launch. |
| OpenAI Codex through local user-owned App Server | Strongest subscription-backed local path; credentials remain local. |
| OpenAI Platform API key | Fully supported BYOK path, but API usage is billed separately from ChatGPT. |
| Anthropic API key, Bedrock, Vertex, or Foundry | Supported commercial integration paths. |
| Claude subscription through `claude -p` or Agent SDK | Do not offer without Anthropic approval. Anthropic explicitly restricts third-party products from offering Claude subscription login or routing requests through consumer subscription credentials. |
| Ollama and local OpenAI-compatible runtimes | Suitable future local-provider paths, subject to model capability and tool compatibility. |

`claude -p` remains useful for a user's own scripts, but its technical support
for headless execution does not override Anthropic's third-party product policy.

## Deferred Implementation Order

When this work is resumed, create a Tier 2 Plan covering auth,
privacy, billing, tool execution, provider policy, and cross-client behavior.
The current recommended order is:

1. Build a hosted App Server proof of concept using stdio and device-code login.
2. Prove isolated per-user credential storage, logout, revocation, idle process
   shutdown, model listing, rate-limit reporting, text streaming, and cancellation.
3. Prove one and multiple dynamic tool calls using existing OpenMates skill
   execution and authorization services.
4. Add token usage, subscription exhaustion, fallback, restart, and error mapping.
5. Integrate a dedicated Codex turn driver without weakening current Main
   Processor controls.
6. Obtain written OpenAI confirmation for the intended general-purpose,
   commercial subscription-backed workload before public launch.
7. Add the local `remote-access` transport using the same App Server adapter.
8. Separately migrate bounded internal automation to `codex exec` with Luna.

## Open Questions

- Will OpenAI support device-code login as a stable production authentication
  method for embedded App Server clients?
- Is general-purpose assistant inference, rather than coding-focused agent work,
  an intended ChatGPT subscription use of App Server?
- What account-risk and revocation requirements will OpenAI require for a hosted
  service that stores per-user Codex refresh tokens?
- Can dynamic tools graduate to a stable protocol before implementation begins?
- Should subscription exhaustion stop the request or offer an explicitly
  preconfigured OpenMates-funded fallback?
- How should subscription-backed main-model usage appear in OpenMates invoices,
  credit estimates, and request histories?
- Which clients may select a local provider when the hosting device is offline?
- Should hosted and local provider connections share one model identity or be
  shown as separate server choices for the same logical model?

## Official References

- [OpenAI Codex authentication](https://developers.openai.com/codex/auth)
- [OpenAI Codex non-interactive mode](https://developers.openai.com/codex/non-interactive-mode)
- [OpenAI Codex SDK](https://developers.openai.com/codex/codex-sdk)
- [OpenAI Codex App Server](https://developers.openai.com/codex/app-server)
- [OpenAI Codex models](https://developers.openai.com/codex/models)
- [OpenAI Codex pricing and limits](https://developers.openai.com/codex/pricing)
- [OpenAI Codex access tokens](https://developers.openai.com/codex/enterprise/access-tokens)
- [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [Anthropic Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Anthropic Claude Code overview](https://code.claude.com/docs/en/overview)
- [Anthropic consumer terms](https://www.anthropic.com/legal/consumer-terms)
