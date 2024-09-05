################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

from celery import Celery
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

if __name__ == '__main__':
    celery.start()