"""An image question must not be mistaken for OpenMates onboarding."""

from types import SimpleNamespace

import pytest

try:
    from backend.apps.ai.processing.preprocessor import _contains_onboarding_trigger_in_user_history
except ImportError as exc:
    pytest.skip(f"Backend dependencies unavailable: {exc}", allow_module_level=True)


# contract-test: supporting surface=rest_api assertions=images-view.request.exact-embed-ref
def test_image_question_does_not_route_to_onboarding():
    history = [SimpleNamespace(role="user", content="What is this? [[embed:photo-1]]")]
    assert _contains_onboarding_trigger_in_user_history(history) is False
