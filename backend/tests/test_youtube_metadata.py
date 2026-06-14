# backend/tests/test_youtube_metadata.py
#
# Regression tests for the shared YouTube metadata provider helpers.
# These helpers sit below web previews, video search, and embed conversion,
# so URL parsing needs to accept browser-generated YouTube share variants.
# The tests stay API-free and only validate deterministic video ID extraction.

import sys
import types

googleapiclient_stub = types.ModuleType("googleapiclient")
googleapiclient_discovery_stub = types.ModuleType("googleapiclient.discovery")
googleapiclient_errors_stub = types.ModuleType("googleapiclient.errors")
googleapiclient_discovery_stub.build = lambda *_args, **_kwargs: None
googleapiclient_errors_stub.HttpError = Exception
sys.modules.setdefault("googleapiclient", googleapiclient_stub)
sys.modules.setdefault("googleapiclient.discovery", googleapiclient_discovery_stub)
sys.modules.setdefault("googleapiclient.errors", googleapiclient_errors_stub)


def _extract_youtube_id_from_url(url: str) -> str | None:
    from backend.shared.providers.youtube.youtube_metadata import extract_youtube_id_from_url

    return extract_youtube_id_from_url(url)


def test_extract_youtube_id_from_watch_url_with_query_params_before_v() -> None:
    url = "https://www.youtube.com/watch?app=desktop&v=j2QEieIiiXg&ra=m"

    assert _extract_youtube_id_from_url(url) == "j2QEieIiiXg"


def test_extract_youtube_id_from_watch_url_with_query_params_after_v() -> None:
    url = "https://www.youtube.com/watch?v=j2QEieIiiXg&app=desktop&ra=m"

    assert _extract_youtube_id_from_url(url) == "j2QEieIiiXg"


def test_extract_youtube_id_rejects_invalid_watch_video_id() -> None:
    url = "https://www.youtube.com/watch?app=desktop&v=short&ra=m"

    assert _extract_youtube_id_from_url(url) is None


def test_extract_youtube_id_from_path_based_urls() -> None:
    assert _extract_youtube_id_from_url("https://youtu.be/j2QEieIiiXg?ra=m") == "j2QEieIiiXg"
    assert _extract_youtube_id_from_url("https://youtube.com/embed/j2QEieIiiXg") == "j2QEieIiiXg"
