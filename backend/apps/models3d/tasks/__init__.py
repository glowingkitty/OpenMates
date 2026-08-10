# backend/apps/models3d/tasks/__init__.py
#
# Models3D Celery task exports. The worker is loaded on the shared media queue
# so it can reuse the existing private S3 and Vault service initialization.

from .generate_task import generate_model_task as generate_model_task

__all__ = ["generate_model_task"]
