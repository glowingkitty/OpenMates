# Live cache verification — 2026-10-25

Implementation `9cc730d1f5`; live backend `4ee83a570a`. Both have the same backend Git tree.

Direct provider adapter probes used synthetic reference text, real credentials and real network requests, with replay/mock mode off. No OpenMates chat model/provider overrides or account model-default changes were used. Each tested provider received a non-streaming request followed by a streaming request with the same prefix. Only numeric usage and sanitized error classifications were retained.

| Provider path | Model | Repeated input | Cache read | Read share |
| --- | --- | ---: | ---: | ---: |
| anthropic | anthropic/claude-haiku-5-5 | 15,087 | 15,071 | 99.9% |
| aws_bedrock | anthropic/claude-sonnet-4-6 | 11,876 | 11,866 | 99.9% |
| cerebras | openai/gpt-oss-120b | 10,741 | 10,624 | 98.9% |
| google | google/gemini-3.8-flash | 12,977 | 8,168 | 62.9% |
| google_ai_studio | google/gemini-3.8-flash | 12,979 | 10,929 | 84.2% |
| groq | openai/gpt-oss-safeguard-20b | 10,741 | 10,496 | 97.7% |
| inception | inception/mercury-3 | 10,712 | 10,394 | 97.0% |
| mistral | mistral/mistral-small-latest | 12,994 | 12,976 | 99.9% |
| openai | openai/gpt-6-luna | 10,677 | 10,674 | 100.0% |
| openrouter | deepseek/deepseek-v4.1-flash | 11,099 | 11,008 | 99.2% |
| together | moonshot/kimi-k3 | 10,763 | 10,624 | 98.7% |

All **11 available cloud provider paths** reported a live hit. There were 25 bounded direct-provider probe attempts, including failed legacy/preview routes. The ratios above describe these controlled repeated-prefix probes, not a guaranteed application-wide hit rate.

OpenAI, Anthropic and Bedrock also reported a positive cache-write count on the initial request and a cache read on the repeated request. Missing implicit cache counters remained unknown instead of being replaced with zero.

Cerebras initially rejected the retired Qwen 235B route with HTTP 404; its current GPT-OSS 120B route passed. Together rejected the old Kimi K2.7 Code route with HTTP 400 and the tested Qwen preview with HTTP 403; the current Kimi K3 catalog route passed. These route availability findings were not counted as cache passes or repaired as unrelated catalog work.

Direct Baseten remains untested at the user’s request until its key is configured. Google MaaS has no registered model route in this environment. Local compatible endpoints were outside these live cloud probes; neither is established by the results above.

## Live OpenMates billing and orchestration

The application run used a fresh disposable account, client encryption and TOTP, an isolated CLI state directory, a new test Project and automatic routing. Its bounded 1,000-credit development fixture grant went through the internal billing ledger; encrypted balances were not patched. No real user account or Project was used for inference.

The first four normal chat turns consumed 66 credits. Saved usage summed to 66, every receipt matched an independent rational calculation from its frozen category rates, and held credits returned to zero. Automatic routing selected Mercury 3 and Gemini 3.8 Flash; cache reads were observed in application receipts. Missing Gemini cache counters correctly selected ordinary-input billing.

A substantive delegated QA request created and completed one real child. Across the parent’s initial and synthesis calls and the child, the shared orchestration recorded 215 spent credits and zero reserved credits. Including earlier turns, seven unique receipts totaled 281 credits, exactly matching the disposable wallet’s 1,000-to-719 decrease.

**Grandchild live coverage is blocked:** the child explicitly reported that `start_sub_chats` was unavailable and performed the requested independent challenge locally. Persisted chat metadata confirms depths 0 and 1 only. The source permits depth 1 to delegate when preprocessing enables subchats, but the child did not receive the tool. This is an orchestration/tool-availability gap; the parent’s prose must not be treated as proof that a grandchild ran. The earlier synthetic depth-2 billing test remains separate evidence.

The direct saved-child follow-up failed with `Timed out waiting for AI response`. It produced no additional charge: the wallet remained at 719 and the seven saved receipts still totaled 281. This was a failed application check even though the recording tool successfully captured the CLI process. The invocation and recording were retained; no paid rerun of that same failure was made.

## Scope boundary

The live provider cache transport checks passed. The recorded parent/child receipt and root-budget checks passed. A complete live grandchild test and a successful direct child continuation are not proven. Repairing delegation/tool availability and child continuation is separate product behavior work; no such policy or client changes were made during this verification. The source and captured failures are sufficient to start that follow-up without another reproduction.
