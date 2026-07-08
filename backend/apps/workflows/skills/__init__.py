# backend/apps/workflows/skills/__init__.py
#
# Skill wrappers for Workflows V1 assistant operations.
# Each wrapper delegates to WorkflowAssistantService so app-skill dispatch cannot
# bypass core workflow validation, lifecycle, or pending-run gates.
