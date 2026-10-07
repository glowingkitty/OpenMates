# Cache pricing comparison — proposed, not activated

For the same request with **100,000 total input tokens, 80,000 cacheable tokens and 1,000 output tokens**, ordinary input/output rates remain unchanged. Output here has no omitted legacy thinking tokens. Charges use the existing single final floor and one-credit minimum.

| Model | Current flat formula on full input | Cold fill | Verified warm read | Warm saving versus flat formula |
|---|---:|---:|---:|---:|
| Gemini 3.8 Flash | 233 | 233 | 73 | 68.7% |
| GPT-6.1 Sol | 639 | 639* | 178* | 72.1% |
| Claude Opus 5.5 | 1316 | 1566 | 366 | 72.2% |
| Mistral Large 4 | 210 | 210 | 64 | 69.5% |

*OpenAI uses the approved policy: include unreported writes in ordinary input and discount only reported reads. Activation still depends on financial checks. A documented supplier write premium can reduce our contribution even when we cannot itemize it.

Anthropic's cold fill costs more because paid five-minute writes replace ordinary input at 1.25× the input tariff. Its existing processing code omitted separately reported cached input; therefore the full-input flat column is a fair tariff comparison, **not a claim that the previous buggy debit was 1,316 credits**. Correct accounting can increase previously undercharged requests. Google thinking correction can also increase previously omitted output charges when the new tariff activates.

For one cold fill plus nine warm turns, modeled average credits are Gemini 89, GPT-6.1 Sol 224.1, Opus 486 and Mistral Large 78.6. Short prompts, expiration, changing context, tool changes and output-heavy requests save less. Explicit Google cache storage is not included and is outside initial production scope.

Raw synthetic provider probes established counter semantics. They did not establish production hit rates, effective paid tariffs for every model, invoice reconciliation, auxiliary processing cost or net credit revenue after fees/FX. These figures are not a margin guarantee or measured live OpenMates CLI debits. Policies and the exact Billing contract were approved on 2026-10-07; deployed before/after verification remains pending.
