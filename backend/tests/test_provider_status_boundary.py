"""Provider monitoring retains supported services without empty status groups."""
import ast
from pathlib import Path

from backend.status.app.config import SERVICE_GROUPS, get_all_service_ids


# contract-test: supporting surface=cli assertions=operational-monitoring.alerts.actionable-low-noise
def test_supported_external_probes_match_public_service_components():
    source = Path("backend/core/api/app/tasks/health_check_tasks.py").read_text()
    module = ast.parse(source)
    targets = next(ast.literal_eval(node.value) for node in module.body
                   if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                   and node.target.id == "EXTERNAL_HTTP_SERVICES")
    expected = {"youtube", "google_maps", "fal", "recraft", "travelpayouts", "flightradar24"}
    ids = {target["service_id"] for target in targets}
    assert ids == expected
    assert ids <= get_all_service_ids()
    assert all(target["url"].startswith("https://") for target in targets)
    assert all(components for _, components in SERVICE_GROUPS)
