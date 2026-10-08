# Activated cache-aware pricing — measured CLI results

Seven verified model tariffs are active on **dev** for normal authenticated personal/team chats: Gemini 3.7/3.8 Flash (AI Studio and Vertex), GPT-6.1 Sol and GPT-6 Luna (direct OpenAI), Claude Sonnet 5 (direct) and Sonnet 4.6 (direct and Bedrock), and Mistral Small 4. Other models remain on their existing ordinary prices until their own tariffs are verified. Production deployment is outside this task.

Charges use provider-reported ordinary input, cache reads, separately reported paid writes where supported, and billable output. OpenAI unreported writes stay included in ordinary input; no estimated write surcharge is applied. Missing cache metrics receive no inferred discount. Per-attempt rates and provider usage are frozen in the encrypted receipt; the operation is floored once with the existing one-credit minimum. Ordinary preprocessing and postprocessing remain bundled. Applied automatic long-chat summaries are separate approved operations. Credit purchases and App Store fees are outside scope.

## Real short conversations

Each test asked why Earth has seasons and made one or two short follow-ups. Prompts and answers were natural language. The table shows main inference charges only, based on saved settled receipts and an independent rational-arithmetic check.

**The flat estimate uses exactly the same observed full input and billable output at the frozen ordinary rates. It is a tariff comparison, not an exact replay of old provider accounting bugs.**

| Provider/model | Requests | Flat estimate, per turn | Actual new credits, per turn | Flat total | New total | Change versus flat |
|---|---:|---|---|---:|---:|---:|
| Google / Gemini 3.8 Flash | 3 | 38 / 39 / 40 | 38 / 39 / 40 | 117 | 117 | 0% |
| OpenAI / GPT-6.1 Sol | 2 | 93 / 93 | 93 / 53 | 186 | 146 | 21.5% lower |
| Anthropic / Claude Sonnet 5 | 2 | 147 / 149 | 164 / 89 | 296 | 253 | 14.5% lower |
| Mistral / Small 4 | 2 | 6 / 6 | 6 / 5 | 12 | 11 | 8.3% lower |

OpenAI reported 6,796 cached input tokens on its follow-up after the stable-prefix boundary fix. Its initial request cost 93 credits and follow-up 53, compared with 93 for each at flat rates: 21.5% saved overall and 43.0% on the follow-up. No web search ran in this final test.

Google did not report cache-read or creation counts; the admitted tariff correctly used ordinary-input billing. Anthropic reported an 11,430-token five-minute write on the first request and an 11,430-token read on the follow-up. The write raises the first request from 147 to 164 credits; the read lowers the follow-up from 149 to 89. Mistral reported 3,984 cached tokens on its follow-up.

### Anthropic's previous undercharge

The previous code omitted Anthropic's separately reported cache tokens. Replaying that old input treatment on these same two responses estimates **80 + 82 = 162 credits**, versus **164 + 89 = 253 now**: a **56.2% increase from the undercharge**. Therefore Anthropic is not cheaper than the old buggy bills in this sample. Its 14.5% cache saving is relative to correctly counting all input at flat rates. This correction pays for supplier usage that was previously unbilled.

### Wallet reconciliation and additional costs

Each fresh Project chat had the existing one-credit Project recommendation. An earlier retained OpenAI verification attempt charged 93 and 102 inference credits (flat estimates 93 and 189, 30.9% lower overall). That follow-up also invoked web search (10 unchanged credits) and therefore incurred two model iterations within one reply; both are included in its 102-credit inference receipt and 189-credit flat estimate. All 206 OpenAI wallet credits were reconciled against retained snapshots, without repeating either paid turn. The verifier was extended to itemize same-chat tool charges rather than treat the additional persisted row as a missing inference receipt.

Google debited 118 wallet credits, the final OpenAI test 147, Anthropic 254 and Mistral 12, including their one-credit recommendations. The final OpenAI test used the deployed stable-prefix fix; other provider tests used the deployed activation source with identical pricing policies. Every completed check left zero held credits. Ordinary processing has no added fee. Configured main token category markup was checked against supplier rates, including OpenAI write liability and its over-272,000-token context tier. These short samples do not establish average hit rates, invoiced supplier costs or a guaranteed whole-conversation margin.

## Verification and source

Activation was published as `f9c1c3733ff7a93ab82c22478e74de6cd0da19ff`; web deployment and seven actual-catalog pricing component cases passed. The OpenAI stable-prefix boundary and CLI accounting verifier repair were published as `258ffdfb0fd251fa236d14c8daddbabdf96bf63a`, after independent review and 60 focused transport, verifier and billing-scope checks. The OpenAI boundary follows the [official prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching), preserving instructions, dynamic context, tools, history and Responses `store=False`.

Private synthetic test captures retain the exact CLI build identity, running backend source generation, admitted frozen tariff versions, provider counts, persisted receipts and wallet snapshots. Public recordings contain only the synthetic conversations. All 18 new recordings (11 real CLI requests, including the earlier verifier-stop attempt, and seven web pricing cases) are retained and uploaded; no paid request is repeated for evidence delivery.
