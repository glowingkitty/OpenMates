# backend/tests/test_workflow_yaml_news_readiness.py
#
# Focused readiness contracts for Workflow YAML app-skill inputs that differ
# from simple top-level scalar fields. This protects CLI-authored workflows from
# stale validation rules that reject real app skill request shapes.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

from backend.core.api.app.services.workflow_yaml_compiler import validate_workflow_yaml


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract,workflows.activation.reachable-side-effect
def test_news_search_requests_array_is_enable_ready() -> None:
    result = validate_workflow_yaml(
        """
title: News workflow
start_when:
  manual: {}
steps:
  - id: news
    use_app_skill: news.search
    input:
      requests:
        - query: OpenMates
          count: 1
  - id: report
    send_chat_message:
      title: Latest news
      blocks:
        - id: news
          source: $nodes.news.output.results
"""
    )

    assert result.draft_valid is True
    assert result.enable_ready is True
    assert result.diagnostics == []


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract,workflows.activation.reachable-side-effect
def test_news_search_missing_requests_blocks_enablement_without_rejecting_draft() -> None:
    result = validate_workflow_yaml(
        """
title: News workflow
start_when:
  manual: {}
steps:
  - id: news
    use_app_skill: news.search
    input: {}
"""
    )

    assert result.draft_valid is True
    assert result.enable_ready is False
    assert [(diagnostic.code, diagnostic.path) for diagnostic in result.diagnostics] == [
        ("REQUIRED_RUNTIME_INPUT", "steps[0].input.requests")
    ]
