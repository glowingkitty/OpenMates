# Cache pricing comparison — proposed, not activated

For the same request with **100,000 total input tokens, 80,000 cacheable tokens and 1,000 output tokens**, ordinary input/output rates remain unchanged. Output here has no omitted legacy thinking tokens. Charges use the existing single final floor and one-credit minimum.

| Model | Current flat formula on full input | Cold fill | Verified warm read | Warm saving versus flat formula |
|---|---:|---:|---:|---:|
| Gemini 3.8 Flash | 233 | 233 | 73 | 68.7% |
| GPT-6.1 Sol | 639 | 639* | 178* | 72.1% |
| Claude Opus 5.5 | 1316 | 1566 | 366 | 72.2% |
| Mistral Large 4 | 210 | 210 | 64 | 69.5% |

*OpenAI uses the approved policy: include unreported writes in ordinary input and discount only reported reads. Activation still depends on verified counters, reservation safety and bundled processing-cost calibration. A documented supplier write premium can reduce our contribution even when we cannot itemize it.

Anthropic's cold fill costs more because paid five-minute writes replace ordinary input at 1.25× the input tariff. Its existing processing code omitted separately reported cached input; therefore the full-input flat column is a fair tariff comparison, **not a claim that the previous buggy debit was 1,316 credits**. Correct accounting can increase previously undercharged requests. Google thinking correction can also increase previously omitted output charges when the new tariff activates.

For one cold fill plus nine warm turns, modeled average credits are Gemini 89, GPT-6.1 Sol 224.1, Opus 486 and Mistral Large 78.6. Short prompts, expiration, changing context, tool changes and output-heavy requests save less. Explicit Google cache storage is not included and is outside initial production scope.

Raw synthetic provider probes established counter semantics. They did not establish production hit rates, effective paid tariffs for every model, invoice reconciliation or auxiliary processing cost. These figures are not a margin guarantee or measured live OpenMates CLI debits. Policies and the exact Billing contract were approved on 2026-10-07; deployed before/after verification remains pending.

The approved OpenAI long-context tier applies to the whole request when inclusive input exceeds 272,000 tokens. GPT-6.1 Sol changes from 165 ordinary-input / 3,300 cached-input / 30 output tokens per credit to 82.5 / 1,650 / 20 respectively. For an illustrative 300,000-token input and 1,000-token output, the old flat tariff is 1,851 credits; the new cold tariff is 3,686, and 80% verified cached input yields 922 credits. This is a modeled example, not a measured CLI result. The higher cold price covers the supplier long-context tier.

Credit purchase prices, App Store fees and purchase-channel differences are outside this change. Supplier-cost comparisons use the existing internal USD 0.001 accounting value per credit. Automatic long-chat summarisation is an approved separate operation, charged only when applied and shown as its own usage entry. Its encrypted intent and settlement passed isolated real-API verification; real activated summarisation remains pending. The modeled main-request savings exclude summary work and do not establish whole-request margin. The first rollout covers normal authenticated personal/team chats; workflows and orchestrated subchats retain their existing billing.


Live verification so far uses inactive cache tariffs. A Gemini 3.8 Flash follow-up reported 16,782 input and 172 output tokens and charged **39 credits**, exactly matching the wallet change. With no reported cached-input count, the new category formula is also **39 credits**; there is no measured discount to claim. The five own-turn supplier calls have a combined upper bound of **USD 0.017752846**, including ordinary preprocessing, generative postprocessing, Jev decisions and translation. Three Google costs are upper bounds rather than exact invoiced costs.

Ordinary processing creates a remaining activation conflict: the generative postprocessor can resend up to 120,000 history tokens even when the main reply receives a cache discount. An illustrative 100k-input Mistral Small 4 turn with 80% verified cached input and 1k output charges **14 credits** after the final floor, while a 100k-input/1k-output uncached Flash-Lite postprocessing call costs **USD 0.0325** before other work. This is a modeled exposure, not an observed loss. The choice between separately billing processing, imposing a safe processing budget, or keeping discounts inactive is pending. The main-only savings table above therefore cannot establish lower total chat costs or safe whole-turn margin.


A real Mistral Small 4 follow-up reported **11,099 ordinary input + 3,984 cached input + 64 output tokens**. Existing billing charged **6 credits**; the proposed main-only category formula is **5 credits**, a 16.7% reduction after rounding. However, its five recorded supplier calls have a combined upper bound of **USD 0.006191602**; ordinary processing must be addressed before that discount is safe. Real OpenAI main charges were **94 and 95 credits**, matching the proposed formula because both calls reported zero cached reads. Each new chat also had a separate one-credit Project recommendation, included in wallet reconciliation rather than confused with main inference.

The earlier Anthropic turns exposed incorrect terminal output and write-retention extraction. The adapter repair was published as `be15805b82e7d3a5f5829c8d07c91db98fdb176a`; a fresh two-turn CLI test completed and reconciled the wallet. The first turn reported **105 ordinary input + 23,950 five-minute cache writes + 190 output tokens**; the follow-up reported **351 ordinary input + 23,950 five-minute cache writes + 226 output tokens**. Both reported zero reads and zero one-hour writes. Existing inactive billing charged **6 and 8 main credits**, omitting the separately reported writes. The proposed category formula gives **182 and 184 main credits**. Correcting this undercharge increases each turn by 176 credits; these two measured requests demonstrate no cache-read savings.

The corrected Anthropic test debited **15 wallet credits**: 14 main credits plus a separate one-credit Project recommendation, with zero holds. Its two main supplier-cost estimates use complete reported counters and total **USD 0.124822**. The five calls per turn have upper bounds of **USD 0.066359750 and USD 0.067195680**, because auxiliary Google cache counters remain unknown. These are configured-rate estimates and ceilings, not reconciled invoices or realized margin. The proposed 366-credit main total remains a simulation: cache tariffs are disabled, and the processing-cost decision and financial checks are still required before activation.

| Measured main operation | Actual existing credits | Proposed category credits | Cache evidence |
|---|---:|---:|---|
| Gemini 3.8 Flash follow-up | 39 | 39 | Read counter absent; no discount inferred |
| GPT-6.1 Sol first / follow-up | 94 / 95 | 94 / 95 | Zero reported reads; writes included in ordinary input |
| Mistral Small 4 first / follow-up | 6 / 6 | 6 / 5 | Follow-up has 3,984 reported cached input tokens |
| Claude Sonnet 5 first / follow-up after counter repair | 6 / 8 | 182 / 184 | Each writes 23,950 tokens for five minutes; zero reads |

These are main-operation comparisons on the same observed usage, not whole-chat quotations. A Project recommendation, an applied automatic summary and any subsequently approved processing charge are separate operations. The proposed column has not been charged to a user.
