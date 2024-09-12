from celery import Celery
from celery.schedules import crontab
import os

redis_url = f"redis://{os.getenv('DRAGONFLY_URL', 'dragonfly:6379')}/0"

celery = Celery('openmates',
             broker=redis_url,
             backend=redis_url,
             include=['server.api.endpoints.tasks.tasks'])

# Optional configuration
celery.conf.update(
    result_expires=3600, # 1 hour
    broker_transport_options = {'visibility_timeout': 3600},  # 1 hour.
)

celery.conf.beat_schedule = {
    # Run every 15 minutes
    'delete-expired-files': {
        'task': 'server.api.endpoints.tasks.tasks.delete_expired_files',
        'schedule': crontab(minute='*/15'),
    }
}

if __name__ == '__main__':
    celery.start()