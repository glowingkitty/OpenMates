# backend/apps/audio/tasks/__init__.py
#
# Celery task registration surface for the Audio app.
# Audio generation shares the app_music queue because no dedicated audio worker
# exists and generated audio needs the same encrypted media services.

from .generate_task import generate_audio_task as generate_audio_task
from .speak_task import speak_audio_task as speak_audio_task
