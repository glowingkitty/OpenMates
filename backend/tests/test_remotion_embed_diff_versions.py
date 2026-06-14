# backend/tests/test_remotion_embed_diff_versions.py
#
# Unit coverage for linear Remotion source history. Restoring an older version
# intentionally truncates later source changes so videos.create does not become
# a git-like branching model.

from backend.apps.videos.remotion_versions import restore_remotion_source_version


def test_restore_older_version_truncates_later_source_changes() -> None:
    restored = restore_remotion_source_version(
        versions=[
            {"version": 1, "source": "v1"},
            {"version": 2, "source": "v2"},
            {"version": 3, "source": "v3"},
        ],
        target_version=2,
    )

    assert restored.current_source_version == 2
    assert restored.source == "v2"
    assert restored.remaining_versions == [
        {"version": 1, "source": "v1"},
        {"version": 2, "source": "v2"},
    ]
    assert restored.truncated_versions == [3]
    assert restored.status == "needs_rerender"
