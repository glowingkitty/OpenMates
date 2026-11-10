"""design.embroidery helpers: request rules, model rework, encrypted storage, billing and result content.

The Celery task in ``backend/apps/design/tasks/embroidery_task.py`` composes these
modules; each one stays importable without Celery so contracts can test it alone.
"""
