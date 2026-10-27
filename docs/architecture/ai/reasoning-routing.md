# Main-answer reasoning recommendations

Jev recommends `LOW`, `MEDIUM`, `HIGH` or `EXTRA_HIGH` in its existing decision
pass, separately from the complexity tier that selects the model chain. Missing
or invalid effort preserves valid routing and the existing model profile. The
serialized recommendation survives continuations and answer recovery.

`servers[].reasoning_control` in provider catalogs declares the native parameter
and canonical-to-native values for each actual model and serving route. Dispatch
resolves it again for every server/model attempt, including fallback and native
history retries. It never infers controls from `reasoning: true` or an adapter-wide
enum. Unknown routes and explicitly fixed variants retain their native behavior.

| Model/route | Native control | Resolution examples |
| --- | --- | --- |
| Gemini on Google | `thinking_level` | EXTRA_HIGH clamps to HIGH |
| Mercury on Inception | `reasoning_effort` | EXTRA_HIGH clamps to high |
| OpenAI direct | `reasoning_effort` | EXTRA_HIGH maps to xhigh where supported; GPT-5.1 clamps high; Pro LOW uses its medium minimum |
| Claude direct/Bedrock | `output_config.effort` | Model-specific levels; adaptive thinking only on declared routes |
| Mistral direct | `reasoning_effort` | Models exposing only high use high |
| GLM 5.3 on Mistral | `reasoning_effort` | MEDIUM maps high; EXTRA_HIGH maps max |
| OpenRouter | `reasoning.effort` | Exact model support from the provider's current model metadata |
| Together | `reasoning_effort` | DeepSeek V4 uses high/max; Kimi K3 uses low/high/max |
| GPT-OSS on Bedrock/OpenRouter | `reasoning_effort` | EXTRA_HIGH clamps high |

Models/routes that expose fixed reasoning without selectable effort, including
Kimi K2.6/K2.7 and OpenRouter GLM 4.7, retain their native behavior. Their presence
in the same adapter does not enable an unsupported field.

With no Jev recommendation, automatic tier defaults remain Mercury MEDIUM for
low text, Gemini 3.8 Flash MEDIUM/HIGH for medium/high, and Gemini 4 Argon HIGH for
max. The low-tier Gemini fallback remains LOW. Main-answer Mercury also defaults
to MEDIUM when selected explicitly; auxiliary Mercury calls retain their existing
settings. Neither a reasoning recommendation nor its default establishes
automatic-routing eligibility or changes an exact model choice.

Mercury LOW/MEDIUM/HIGH attempts have 5/15/60 second deadlines through the first
substantive text or tool output and combined reasoning-plus-answer completion
caps of 8192/16384/32768 tokens. Usage/thinking metadata does not satisfy the
deadline, and the generic stream watchdog cannot shorten it. Smaller existing
model, wallet, anonymous, workflow or orchestration limits still win before
reservation and actual provider admission. EXTRA_HIGH uses HIGH's limits.

The [Mercury comparison](../../apis/mercury-reasoning-comparison-2026-10-22.md)
explains these defaults. The owning contract is `feature.ai-model-routing@9`.
