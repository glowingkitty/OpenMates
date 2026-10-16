"""History diffs replay exact committed runtime text without creating snapshots."""

import pytest

from backend.core.api.app.services.embed_diff_service import (
    apply_patch,
    apply_patch_exact,
    build_committed_version_patch,
    parse_unified_diff,
)


# contract-test: supporting surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.parametrize('original,committed', [
    ('first\nsecond\nthird', 'first\nupdated\nthird'),
    ('old\n', 'new\n'), ('same', 'same'),
])
def test_committed_history_patch_replays_exactly(original, committed):
    patch = build_committed_version_patch(original, committed)
    result = apply_patch_exact(original, parse_unified_diff(patch, 'embed'))
    assert result.success
    assert result.new_content == committed


# contract-test: supporting surface=rest_api assertions=storage.versions.bounded-reconstruction
def test_fuzzy_runtime_diff_becomes_an_exact_history_patch():
    original = 'first\nsecond\nthird'
    raw = parse_unified_diff('@@ -1 +1 @@\n-second\n+updated', 'embed')
    assert not apply_patch_exact(original, raw).success
    actual = apply_patch(original, raw)
    assert actual.success and actual.tier == 2
    patch = build_committed_version_patch(original, actual.new_content)
    replay = apply_patch_exact(original, parse_unified_diff(patch, 'embed'))
    assert replay.success
    assert replay.new_content == actual.new_content == 'first\nupdated\nthird'


# contract-test: supporting surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.parametrize('old_start,expected', [(0, 'new\nfirst\nlast'), (1, 'first\nnew\nlast')])
def test_zero_count_insertions_use_the_declared_boundary(old_start, expected):
    patch = f'@@ -{old_start},0 +{old_start + 1} @@\n+new'
    result = apply_patch_exact('first\nlast', parse_unified_diff(patch, 'embed'))
    assert result.success
    assert result.new_content == expected
