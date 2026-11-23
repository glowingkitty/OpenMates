from pathlib import Path

from backend.apps.ai.daily_inspiration.schemas import (
    drop_unsupported_inspirations,
    has_complete_daily_inspiration_set,
)
from backend.apps.ai.daily_inspiration.wiki_suggestions import build_wiki_inspirations

REPO_ROOT = Path(__file__).resolve().parents[2]


# contract-test: supporting surface=rest_api assertions=daily-inspiration.encrypted-persistence
def test_authenticated_persistence_requires_exactly_three_video_and_three_wiki() -> None:
    complete = [
        *({"content_type": "video"} for _ in range(3)),
        *({"content_type": "wiki"} for _ in range(3)),
    ]

    assert has_complete_daily_inspiration_set(complete) is True
    assert has_complete_daily_inspiration_set(complete[:-1]) is False
    assert has_complete_daily_inspiration_set(
        complete + [{"content_type": "feature"} for _ in range(4)]
    ) is False
    assert has_complete_daily_inspiration_set(
        [{"content_type": "wiki"} for _ in range(4)]
        + [{"content_type": "feature"} for _ in range(2)]
    ) is False


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
def test_legacy_feature_records_are_filtered_out() -> None:
    legacy = [
        {"content_type": "video"},
        {"content_type": "feature"},
        {"content_type": "wiki"},
        {},
    ]

    kept = drop_unsupported_inspirations(legacy)

    assert [item.get("content_type") for item in kept] == ["video", "wiki", None]
    assert all(item.get("content_type") != "feature" for item in kept)


# contract-test: supporting surface=rest_api assertions=daily-inspiration.authenticated-fallback-content
def test_feature_suggestions_module_is_removed() -> None:
    assert not (
        REPO_ROOT / "backend/apps/ai/daily_inspiration/feature_suggestions.py"
    ).exists()


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,daily-inspiration.authenticated-fallback-content
def test_daily_inspiration_quotas_share_the_six_card_3_3_contract() -> None:
    personalized_source = (
        REPO_ROOT / "backend/core/api/app/tasks/daily_inspiration_tasks.py"
    ).read_text()
    selector_source = (
        REPO_ROOT / "backend/core/api/app/tasks/default_inspiration_tasks.py"
    ).read_text()
    route_source = (
        REPO_ROOT / "backend/core/api/app/routes/default_inspirations.py"
    ).read_text()

    assert 'DEFAULT_TYPE_QUOTAS = {"video": 3, "wiki": 3}' in selector_source
    assert "DAILY_VIDEO_COUNT = 3" in personalized_source
    assert "DAILY_WIKI_COUNT = 3" in personalized_source
    assert "DAILY_INSPIRATION_COUNT = DAILY_VIDEO_COUNT + DAILY_WIKI_COUNT" in personalized_source
    assert "_DEFAULT_INSPIRATION_COUNT = 6" in route_source
    assert "feature_suggestions" not in personalized_source + selector_source + route_source
    assert 'public:default_inspirations:v20:' in route_source
    assert 'public:default_inspirations:v20:' in selector_source


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
def test_static_wiki_fallbacks_do_not_include_redirect_only_murmuration() -> None:
    inspirations = build_wiki_inspirations(count=10)
    wiki_titles = [inspiration.wiki.wiki_title for inspiration in inspirations if inspiration.wiki]

    assert "Murmuration" not in wiki_titles
    assert "Collective_animal_behavior" in wiki_titles


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
def test_default_selection_and_endpoint_filter_video_text_media_mismatches() -> None:
    selector_source = (
        REPO_ROOT / "backend/core/api/app/tasks/default_inspiration_tasks.py"
    ).read_text()
    route_source = (
        REPO_ROOT / "backend/core/api/app/routes/default_inspirations.py"
    ).read_text()

    assert "is_inspiration_media_coherent" in selector_source
    assert "is_inspiration_media_coherent" in route_source


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
def test_anonymous_defaults_have_no_paid_review_entry_points() -> None:
    import ast
    source = (REPO_ROOT / "backend/core/api/app/routes/default_inspirations.py").read_text()
    forbidden = {"review_candidates", "review_copy_candidates", "call_semantic_model", "call_preprocessing_llm"}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else "")
            assert name not in forbidden
    assert "is_inspiration_media_coherent(record)" in source
