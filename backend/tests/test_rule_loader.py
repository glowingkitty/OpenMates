"""Rule document boundaries and guide-level application semantics."""

import pytest

from backend.shared.python_utils.rule_loader import (
    applied_rule_set_key, load_app_rules, parse_rule_md, rules_prompt,
)

GUIDE = """---
title: Svelte coding rules
description: Reliable component state and effects.
when_to_use: Writing Svelte components.
---
- Derive dependent state.
- Clean up subscriptions.
"""


# contract-test: supporting surface=rest_api assertions=rules.definition.guide-format,rules.precedence.obligations
def test_guide_has_one_identity_and_revision_changes_with_content():
    first = parse_rule_md(GUIDE, rule_id="rule-1", source="personal")
    second = parse_rule_md(GUIDE + "- Test visible behavior.\n", rule_id="rule-1", source="personal")
    assert first.title == "Svelte coding rules"
    assert first.body.count("- ") == 2
    assert first.revision != second.revision
    assert "Derive dependent state" not in first.discovery_text()
    assert first.revision in rules_prompt([first])
    assert "grant no permission" in rules_prompt([first])
    assert applied_rule_set_key([first, second]) == applied_rule_set_key([second, first])


@pytest.mark.parametrize("document", [
    "body without header", GUIDE.replace("title: Svelte coding rules", "title: ''"),
    GUIDE.replace("description: Reliable", "title: Duplicate\ndescription: Reliable"),
    GUIDE.replace("description: Reliable component state and effects.", "description: &ref Reliable\nwhen_to_use: *ref"),
    GUIDE + "x" * 24_000, GUIDE.split("---\n", 2)[0] + "---\ntitle: A\ndescription: B\nwhen_to_use: C\n---\n",
])
# contract-test: supporting surface=rest_api assertions=rules.definition.guide-format
def test_invalid_or_ambiguous_rule_is_rejected(document):
    with pytest.raises(ValueError):
        parse_rule_md(document, rule_id="rule-1", source="personal")


# contract-test: supporting surface=rest_api assertions=rules.ownership.encrypted-custom
def test_project_binding_is_required_and_app_paths_cannot_escape(tmp_path):
    with pytest.raises(ValueError):
        parse_rule_md(GUIDE, rule_id="rule-1", source="project")
    with pytest.raises(ValueError):
        load_app_rules(["../private"], apps_root=tmp_path)
    guide = parse_rule_md(GUIDE, rule_id="rule-1", source="project", project_id="project-a")
    assert guide.project_id == "project-a"


# contract-test: supporting surface=rest_api assertions=rules.definition.guide-format
def test_shipped_guides_have_expected_whole_topic_granularity():
    guides = load_app_rules(["code", "design"])
    assert len(guides) == 6
    assert {rule.title for rule in guides} >= {"Svelte coding rules", "Python coding rules", "Mobile first design", "Accessibility best practices"}
    assert all(rule.body.count("- ") >= 5 for rule in guides)
    assert all(rule.source == "app" for rule in guides)


@pytest.mark.parametrize("change", [
    "unknown: field", "description: [not, text]", "<<: {description: merged}",
    "description: *missing", "description: [unterminated",
])
# contract-test: supporting surface=rest_api assertions=rules.definition.guide-format
def test_malformed_or_unsupported_frontmatter_rejected(change):
    document = GUIDE.replace("description: Reliable component state and effects.", change)
    with pytest.raises(ValueError):
        parse_rule_md(document, rule_id="r", source="personal")


# contract-test: supporting surface=rest_api assertions=rules.ownership.encrypted-custom,rules.transparency.applied-set
def test_model_rejects_forged_source_binding_and_snapshot_mutation():
    rule = parse_rule_md(GUIDE, rule_id="r", source="personal")
    with pytest.raises(ValueError):
        type(rule).model_validate({**rule.model_dump(), "app_id": "code"})
    with pytest.raises(ValueError):
        rule.body = "different injected text"


# contract-test: supporting surface=rest_api assertions=rules.ownership.encrypted-custom
def test_app_rule_symlink_cannot_escape_catalog(tmp_path):
    catalog = tmp_path / "apps"
    directory = catalog / "code" / "rules"
    directory.mkdir(parents=True)
    private = tmp_path / "private.md"
    private.write_text(GUIDE)
    (directory / "escaped.md").symlink_to(private)
    with pytest.raises(ValueError):
        load_app_rules(["code"], apps_root=catalog)


# contract-test: supporting surface=rest_api assertions=rules.selection.focus-aware
def test_app_symlink_cannot_load_an_ineligible_app_rule(tmp_path):
    code = tmp_path / "code" / "rules"
    design = tmp_path / "design" / "rules"
    code.mkdir(parents=True)
    design.mkdir(parents=True)
    inaccessible = design / "private.md"
    inaccessible.write_text(GUIDE)
    (code / "borrowed.md").symlink_to(inaccessible)
    with pytest.raises(ValueError):
        load_app_rules(["code"], apps_root=tmp_path)
