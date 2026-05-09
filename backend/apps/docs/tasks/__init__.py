# backend/apps/docs/tasks/__init__.py
#
# Exposes the document generation Celery task so celery_config.py can discover
# it by importing this module. The task converts structured docx_model payloads
# into encrypted DOCX artifacts and browser preview screenshots.
from .generate_task import generate_docx_task as generate_docx_task
