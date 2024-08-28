from celery import Celery

app = Celery('openmates',
             broker='redis://dragonfly:6379/0',
             backend='redis://dragonfly:6379/0',
             include=['server.api.endpoints.tasks.tasks'])

# Optional configuration
app.conf.update(
    result_expires=3600, # 1 hour
    broker_transport_options = {'visibility_timeout': 3600},  # 1 hour.
)

if __name__ == '__main__':
    app.start()