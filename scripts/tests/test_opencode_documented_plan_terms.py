"""Tests for Plan Mode terms loaded from canonical instruction documents.

The Plan prompt remains concise while the SDD guide owns implementation-demo
details. Only the explicit demonstration terms may be satisfied by that guide;
all other deterministic Plan Mode terms remain mandatory in the prompt itself.
"""

from __future__ import annotations

# contract-test-file: tooling

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]


def load_audit():
    path = ROOT / "scripts" / "audit_opencode_plan_workflow.py"
    spec = importlib.util.spec_from_file_location("opencode_documented_plan_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_demonstration_terms_may_come_from_loaded_sdd_guide(tmp_path: Path) -> None:
    audit = load_audit()
    guide = tmp_path / "guide.md"
    guide.write_text("narration outline frame-only review OpenCode response-media", encoding="utf-8")
    audit.REPO_ROOT = tmp_path
    audit.REQUIRED_INSTRUCTIONS = {"guide.md"}
    audit.PLAN_PROMPT_TERMS = {"schema_version", "narration outline", "frame-only review", "OpenCode response-media"}
    config = {
        "instructions": ["guide.md"],
        "agent": {
            "plan": {
                "mode": "primary",
                "prompt": "schema_version",
                "permission": {
                    "question": "allow",
                    "edit": {"*": "deny", "docs/plans/**/plan.yml": "allow"},
                },
            }
        },
    }

    assert audit.audit_config(config) == []
