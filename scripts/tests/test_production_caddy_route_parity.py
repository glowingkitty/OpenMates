# contract-test-file: infrastructure
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
