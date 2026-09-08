# Replay-only parity for authenticated REST inference submissions.
#
# The browser already receives account-bound signatures at its server boundary.
# REST callers must use the same strict configured test-account predicate, never
# client identity metadata. This helper neither authorizes real/record execution
# nor bypasses API scopes, credits, output safety, or worker signature validation.
# See docs/architecture/live-mock-testing.md and isolated-github-tests.md.

from backend.shared.python_utils.e2e_user_detection import is_configured_test_account_profile
from backend.shared.testing.mock_context import (
    _LIVE_MARKER_PATTERN,
    _is_production_environment,
    detect_live_marker,
    sign_live_marker,
)
import os


async def prepare_rest_replay_messages(messages, user_id, cache_service, directus_service=None):
    """Sign only a trailing MOCK marker on the last user message, server-side."""
    marked = [(index, message) for index, message in enumerate(messages)
              if isinstance(message, dict) and isinstance(message.get('content'), str)
              and '<<<TEST_LIVE_' in message['content']]
    if not marked:
        return messages
    if _is_production_environment() or os.getenv('MOCK_EXTERNAL_APIS') != 'true' or not user_id:
        raise ValueError('REST replay controls are disabled')
    profile = await cache_service.get_user_by_id(user_id) if cache_service else None
    if not profile and directus_service:
        success, profile, _ = await directus_service.get_user_profile(user_id)
        if not success:
            profile = None
    if not is_configured_test_account_profile(profile):
        raise ValueError('REST replay requires a configured test account')
    result = list(messages)
    for index, message in marked:
        content = message['content']
        matches = list(_LIVE_MARKER_PATTERN.finditer(content))
        if (len(matches) != 1 or content.count('<<<TEST_LIVE_') != 1
                or matches[0].group(1) != 'MOCK' or matches[0].group(3)
                or message.get('role') != 'user' or index != len(messages) - 1
                or content[matches[0].end():].strip()):
            raise ValueError('REST supports only a trailing replay marker on the current user turn')
        match = matches[0]
        if match.group(4) or match.group(5):
            # Never refresh stale or foreign signatures submitted by a client.
            if detect_live_marker(content, user_id) is None:
                raise ValueError('Invalid REST replay signature')
            continue
        signed = sign_live_marker(match.group(0), user_id, is_allowlisted_test_account=True)
        if not signed:
            raise ValueError('REST replay signing rejected')
        result[index] = {**message, 'content': content[:match.start()] + signed}
    return result
