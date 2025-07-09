# Server architecture

> This is the planned architecture. Keep in mind there can still be differences to the current state of the code.

## API server

- docker compose consisting of
	- core-api docker
	- core-api-task-worker docker
	- directus docker
	- dragonfly docker
	- grafana docker
	- Loki docker
	- Prometheus docker
	- celery task-scheduler docker
	- app-ai docker
		- with docker network internal fast api endpoints for each skill and each focus mode
		- /skill/ask
			- used every time a user is messaging a digital team mate
	- app-ai-task-worker docker
		- celery task worker for processing longer running tasks (like /skill/ask)
	- for each additional app, we add two dockers:
		- app-{appname} docker
			- with docker network internal fast api endpoints for each skill and each focus mode
		- app-{appname}-task-worker docker
			celery task worker for processing longer running tasks
		- for the apps web, videos, sheets, docs, etc.


## uploads server

- isolated docker environment to process files
- public /upload endpoint
	- validate user
	- check if file is within file size limit
	- check for harmful uploaded files
	- if pdf or image file: create preview image
	- upload preview and original to S3 hetzner and return file id to frontend?
- public /files endpoint
	- validate user
	- gets hetzner s3 url for file and does a 302 redirect to the hetzner s3 url
- public /preview endpoint
	- validate use
	- checks if hetzner s3 url for preview image for the file exists and if so, makes 302 forward to the hetzner s3 url

## preview server

- docker / docker compose with fastapi
- public /image-proxy/?url={original_image_url} endpoint:
	- validates user (?)
	- if image from url is cached in memory or disk, return image
	- else download first image, save it to cache or disk and return it
- public or internal /web/metadata endpoint?