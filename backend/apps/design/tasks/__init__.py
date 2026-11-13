"""Design Celery tasks; loaded on the shared media worker (app_images queue)."""

from .embroidery_task import embroidery_task as embroidery_task

__all__ = ["embroidery_task"]
