# contract-test-file: infrastructure
# Guard production route coverage and first-party credentialed CORS together.
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def test_production_preserves_openmates_route_parity_and_credentialed_workspace():
    dev = (ROOT / "deployment/dev_server/Caddyfile").read_text()
    prod = (ROOT / "deployment/prod_server/Caddyfile").read_text()
    def paths(text):
        return {value for line in text.splitlines() if (match := re.match(r"\s*(?:@[\w-]+\s+)?path\s+([^#]+)", line)) for value in match[1].split() if value.startswith("/v1/")}
    development_only = {"/v1/experiment/videocall", "/v1/test-recordings", "/v1/test-recordings/*"}
    assert not (paths(dev) - paths(prod) - development_only)
    assert not (paths(prod) & development_only)
    for matcher in ("@apps_workspace_options", "@apps_workspace_actual"):
        assert matcher + " {" in prod
        assert "handle " + matcher + " {" in prod
    assert prod.count(r"header_regexp apps_workspace_origin Origin ^https://(app\.)?openmates\.org$") == 2
    assert "*.openmatesusercontent.org {" in prod
    assert "dns gandi" in prod


def test_memory_suggestion_routes_are_reachable_for_the_web_app():
    """The web app calls these with the session cookie; an unlisted path is cut off by the proxy."""
    for name in ("dev_server", "prod_server"):
        text = (ROOT / "deployment" / name / "Caddyfile").read_text()
        listed = [line for line in text.splitlines() if "/v1/memory-suggestions/*" in line]
        # Origin-checked webapp paths, the CORS preflight matcher and the actual-request matcher.
        assert len(listed) == 3, name


def test_image_enhance_routes_are_reachable_for_the_web_app():
    """POST /v1/images/enhance and GET /v1/images/enhance/{operation_id} are first-party session routes."""
    for name in ("dev_server", "prod_server"):
        text = (ROOT / "deployment" / name / "Caddyfile").read_text()
        listed = [line for line in text.splitlines() if "/v1/images/enhance /v1/images/enhance/*" in line]
        assert len(listed) == 3, name


def test_user_revision_commit_is_reachable_for_the_web_app():
    """POST /v1/embeds/{embed_id}/user-revisions is a credentialed first-party session route."""
    route = "/v1/embeds/*/user-revisions"
    for name, expected in (("dev_server/Caddyfile", 3), ("prod_server/Caddyfile", 3), ("Caddyfile.example", 2)):
        text = (ROOT / "deployment" / name).read_text()
        listed = [line for line in text.splitlines() if route in line.split()]
        # dev/prod: origin-checked webapp paths, CORS preflight and actual request; the example has no @webapp_paths.
        assert len(listed) == expected, name
        for matcher in ("@webapp_general_options {", "@webapp_actual {"):
            block = text.split(matcher, 1)[1].split("}", 1)[0]
            assert route in block.split(), (name, matcher)
