"""Compatibility names for legacy Rule callers; canonical definitions are Memories."""
from backend.shared.python_utils.memory_loader import (
    MAX_MEMORY_CHARS as MAX_RULE_CHARS, MemoryDefinition as RuleDefinition,
    applied_memory_set_key as applied_rule_set_key, load_app_memories as load_app_rules,
    memories_prompt as rules_prompt, parse_memory_md,
)

__all__ = ["MAX_RULE_CHARS", "RuleDefinition", "applied_rule_set_key", "load_app_rules", "rules_prompt", "parse_rule_md"]

def parse_rule_md(document, *, rule_id, source, app_id=None, project_id=None):
    return parse_memory_md(document, memory_id=rule_id, source=source, app_id=app_id, project_id=project_id)
