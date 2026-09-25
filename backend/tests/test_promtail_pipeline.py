"""Static contracts for the OpenObserve Promtail ingestion boundary."""

# contract-test-file: infrastructure

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
PROMTAIL_CONFIG = REPO_ROOT / "backend/core/monitoring/promtail/promtail-config.yaml"
CLI_SERVER = REPO_ROOT / "frontend/packages/openmates-cli/src/server.ts"


def _container_pipeline() -> list[dict]:
    config = yaml.safe_load(PROMTAIL_CONFIG.read_text())
    job = next(item for item in config["scrape_configs"] if item["job_name"] == "container-logs")
    return job["pipeline_stages"]


def test_container_empty_lines_are_dropped_at_the_decoded_target_boundary() -> None:
    pipeline = _container_pipeline()

    assert pipeline[0] == {
        "drop": {
            "expression": r"^\s*$",
        }
    }


def test_selfhost_template_keeps_the_same_docker_empty_line_boundary() -> None:
    source = CLI_SERVER.read_text()
    container_job = source.split("  - job_name: container-logs", 1)[1].split("`;", 1)[0]

    drop_stage = container_job.index("      - drop:")
    drop_expression = container_job.index("          expression: '^\\\\s*$'")
    json_stage = container_job.index("      - json:")

    assert drop_stage < drop_expression < json_stage
    assert "      - docker: {}" not in container_job
