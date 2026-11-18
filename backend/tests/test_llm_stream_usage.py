"""Token counts are read from every provider's usage chunk, so no author call is billed as zero."""

from types import SimpleNamespace

from backend.apps.ai.llm_providers.google_client import GoogleUsageMetadata
from backend.apps.ai.llm_providers.mistral_client import MistralUsage
from backend.shared.python_utils.llm_stream_usage import stream_usage_tokens


# contract-test: supporting surface=rest_api assertions=videos-generate.billing.metered
def test_text_chunks_are_not_usage():
    assert stream_usage_tokens("some text") is None
    assert stream_usage_tokens(SimpleNamespace(other=1)) is None


# contract-test: supporting surface=rest_api assertions=videos-generate.billing.metered
def test_openai_and_anthropic_shape():
    assert stream_usage_tokens(SimpleNamespace(input_tokens=120, output_tokens=45)) == (120, 45)
    assert stream_usage_tokens(SimpleNamespace(input_tokens=None, output_tokens=7)) == (0, 7)


# contract-test: supporting surface=rest_api assertions=videos-generate.billing.metered
def test_google_shape_counts_thinking_as_output():
    usage = GoogleUsageMetadata(prompt_token_count=400, candidates_token_count=250, thoughts_token_count=90,
                                total_token_count=740)
    assert stream_usage_tokens(usage) == (400, 340)


# contract-test: supporting surface=rest_api assertions=videos-generate.billing.metered
def test_google_shape_without_thinking():
    usage = GoogleUsageMetadata(prompt_token_count=400, candidates_token_count=250)
    assert stream_usage_tokens(usage) == (400, 250)


# contract-test: supporting surface=rest_api assertions=videos-generate.billing.metered,ai-model-routing.skills.internal-llm-follows-settings
def test_chat_completions_shape_of_mistral():
    """A user's saved Mistral model authoring a skill step is billed for the tokens it reported."""
    usage = MistralUsage(prompt_tokens=812, completion_tokens=1_204, total_tokens=2_016, reasoning_tokens=300)
    assert stream_usage_tokens(usage) == (812, 1_204)
    assert stream_usage_tokens(SimpleNamespace(prompt_tokens=None, completion_tokens=9)) == (0, 9)
