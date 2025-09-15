# AI model selection architecture

## Currently

Under /backend/providers/ each LLM provider (the creator of the model, not the server provider) has their own .yml file, with an overview of all available models, their costs and optional server options (including server options like AWS Bedrock, Azure AI, OpenRouter). By default the API from the provider itself will be used, unless a model’s `default_server` is set to another server. For example, Claude 3.7 Sonnet is configured to use AWS Bedrock by default.

Under /backend/apps/ai/llm_providers we have the scripts for the APIs for each provider and for optional server options.

Under /backend/apps/ai/app.yml we define the default LLM models for simple requests and complex requests, as well as the harmful content detection threshold.

### Default models

Simple requests: Mistral Medium
Complex requests: Claude 3.7 Sonnet (via AWS Bedrock)

### Model observations

#### GPT-OSS-120b

Really really wants to add tables to all responses. Can be too disturbing/annoying in responses.
While processing is fast, its still noticably hallucinating sometimes.
Also, since its a reasoning model, the responses tend to be very long and not concise.

#### GPT-5

Good quality output, but slow performance.
Slow performance is made worse since GPT-5 is reasoning first, producing extra tokens first which aren't visible to the user. Resulting in bad UX. Claude Sonnet in comparison is not much faster, but feels faster because of no reasoning step.
Performance comparison (data from OpenRouter from August 8 2025, but should be representative enough):

- GPT-5 via OpenAI (regular mode, not priority):
	37.51 tokens per second average
- Claude 3.7 Sonnet via AWS Bedrock:    39.62 tokens per second average
- Claude 4 Sonnet via AWS Bedrock:      53.15 tokens per second average
- Mistral Medium 3 via Mistral:         75.95 tokens per second average
- Gemini 2.5 Pro via Vertex AI:         88.20 tokens per second average

#### Mistral Medium 3

Seems reasonable for simple questions. Speed is good.

#### Quen3 256b

Good responses in many cases, but unusable for everything related to China sensitive topics like Taiwan.

## Planned

In the future the model selection could be rebuild by allowing the pre-processing script & LLM to auto select the right model for the request based on various parameters, from rate limits, reasoning, cost, speed (also considering that for example gpt-5 has a priority mode for faster inference, for more money), best_for_scenarios and other characteristics. Output should be top 3 best models for the task (best first). So if model isnt accessible or gets unexpected rate limit error, we have the option to fall back to another model.