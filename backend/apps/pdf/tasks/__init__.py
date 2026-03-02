# backend/apps/pdf/tasks/__init__.py
# Exposes the PDF processing Celery task so celery_config.py can discover it
# by importing this module.
from .process_task import process_pdf_task as process_pdf_task
