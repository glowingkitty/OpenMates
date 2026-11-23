# contract-test-file: tooling
"""Check that the published and development manifests follow the canonical Compose input."""

import pytest
import yaml

from scripts.sync_core_compose import DEV_OVERRIDES, ROOT, SOURCE, render_dev, synchronize


def test_checked_in_core_compose_outputs_match_source():
    synchronize(check=True)


def test_dev_inherits_new_services_and_routing_queue_changes():
    source = yaml.safe_load((ROOT / SOURCE).read_text())
    overrides = (ROOT / DEV_OVERRIDES).read_text()
    source["services"]["new-service"] = {"image": "alpine"}
    source["services"]["app-ai-routing-worker"]["environment"]["CELERY_QUEUES"] = "moved_queue"

    generated = yaml.safe_load(render_dev(yaml.safe_dump(source), overrides))

    assert generated["services"]["new-service"] == {"image": "alpine"}
    routing_worker = generated["services"]["app-ai-routing-worker"]
    assert routing_worker["environment"]["CELERY_QUEUES"] == "moved_queue"
    assert "--queues=moved_queue " in routing_worker["command"][2]


def test_dev_overrides_cannot_keep_a_removed_service():
    source = (ROOT / SOURCE).read_text()
    with pytest.raises(ValueError, match="unknown core services: .*obsolete"):
        render_dev(source, "services: {obsolete: {image: alpine}}")
