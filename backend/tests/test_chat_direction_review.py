"""The shared real-provider entry parses reviews without treating failures as decline proof."""
# contract-test-file: infrastructure
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import chat_direction_review as review
from backend.apps.ai.processing.chat_direction import DirectionAuthority, DirectionAssessment, assemble_direction_context


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments,error,verified,warranted', [
    ({'warranted': True, 'instruction': 'Return to the actual goal.'}, None, True, True),
    ({'warranted': False, 'instruction': ''}, None, True, False),
    ({}, 'provider failed', False, False),
])
async def test_shared_generative_reviewer_requires_actual_typed_provider_result(monkeypatch, arguments, error, verified, warranted):
    provider = AsyncMock(return_value=SimpleNamespace(arguments=arguments, error_message=error))
    monkeypatch.setattr(review, 'call_preprocessing_llm', provider)
    context = assemble_direction_context(authority=DirectionAuthority('owner', 'chat', 'turn', 'goal'),
        message_history=[{'role': 'user', 'content': 'Fix login'}], recent_actions=[{'summary': 'Unrelated work'}])
    result = await review.review_chat_direction(context, DirectionAssessment('material_drift', context.fingerprint),
        task_id='synthetic-review', model_id='generative-model', secrets_manager=None)
    assert result.warranted is warranted and result.provider_verified is verified
    args = provider.await_args.kwargs
    assert args['model_id'] == 'generative-model' and args['allow_retries'] is False
    assert args['observability_purpose'] == 'chat_direction_review'
    assert 'does not represent user approval' not in result.instruction  # Framing occurs only at delivery.
