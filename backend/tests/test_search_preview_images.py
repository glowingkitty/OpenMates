"""
Search preview image metadata regression tests.
Checks that child thumbnail fields survive in lightweight parent previews.
Reuses the existing metadata suite dependency stubs for this isolated unit check.
No provider requests or product integration stack are involved.
Architecture: docs/architecture/embeds.md
"""
from backend.tests import test_skill_preview_metadata as _metadata_test_setup  # noqa: F401


# contract-test: supporting surface=gui.web assertions=web-search.surface-parity
def test_news_search_parent_preview_metadata_contains_favicon_capable_results() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    metadata = EmbedService._build_parent_preview_metadata(
        "news",
        "search",
        [
            {
                "title": "OpenMates raises privacy bar",
                "url": "https://news.example/openmates",
                "description": "Long article text that should stay child-only",
                "favicon": "https://news.example/favicon.ico",
                "published_date": "2026-06-21",
                "thumbnail_original": "https://news.example/photo.jpg",
                "thumbnail_src": "https://news.example/small.jpg",
                "raw_provider_payload": {"large": "blob"},
            }
        ],
    )

    assert metadata == {
        "preview_results": [
            {
                "title": "OpenMates raises privacy bar",
                "url": "https://news.example/openmates",
                "favicon": "https://news.example/favicon.ico",
                "published_date": "2026-06-21",
                "preview_image_url": "https://news.example/photo.jpg",
            }
        ]
    }



# contract-test: supporting surface=gui.web assertions=web-search.surface-parity
def test_search_parent_preview_metadata_normalizes_nested_thumbnails() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    for app_id in ("web", "news"):
        metadata = EmbedService._build_parent_preview_metadata(app_id, "search", [{
            "url": "https://example.org/article",
            "thumbnail": {"original": "https://example.org/photo.jpg", "extra": "omitted"},
        }])
        assert metadata["preview_results"] == [{
            "url": "https://example.org/article",
            "preview_image_url": "https://example.org/photo.jpg",
        }]
