import os
import docker
import sys
import logging
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from typing import List, Optional, Dict
import json
import yaml

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Docker client
client = docker.from_env()

# FastAPI app
app = FastAPI()

# Security
API_KEY = os.environ.get("CONTAINER_MANAGER_SECRET_KEY")
api_key_header = APIKeyHeader(name="X-API-Key")

# Construct the path to app_docker_containers.json
current_dir = os.path.dirname(os.path.abspath(__file__))
server_dir = os.path.dirname(current_dir)
# Load app docker container configs from YAML
yaml_path = os.path.join(server_dir, 'apps', 'apps.yml')

try:
    with open(yaml_path, 'r') as f:
        app_docker_containers = yaml.safe_load(f)['apps']
    logger.info(f"Successfully loaded apps.yml from {yaml_path}")
except FileNotFoundError:
    logger.error(f"apps.yml not found at {yaml_path}")
    logger.error("Exiting container manager...")
    sys.exit(1)
except yaml.YAMLError:
    logger.error(f"Error decoding apps.yml at {yaml_path}")
    logger.error("Exiting container manager...")
    sys.exit(1)

class ContainerRequest(BaseModel):
    name: str
    image: str
    environment: Optional[Dict[str, str]] = None
    volumes: Optional[Dict[str, str]] = None
    network: Optional[str] = None
    extra_hosts: Optional[Dict[str, str]] = None

def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key

def build_predefined_containers():
    logger.info("Checking and building predefined containers...")
    for app_name, container in app_docker_containers.items():
        try:
            # Check if the container already exists
            existing_container = client.containers.list(filters={"name": container['container_name']})
            if existing_container:
                logger.info(f"Container {container['container_name']} already exists")
                continue

            # Try to get the image using the container name as the tag
            client.images.get(container['container_name'])
            logger.info(f"Image for {container['container_name']} already exists")
        except docker.errors.ImageNotFound:
            logger.info(f"Image for {container['container_name']} not found. Attempting to build...")
            try:
                # Construct the build path
                build_path = os.path.join(server_dir, container['build']['context'])
                if not os.path.isdir(build_path):
                    raise ValueError(f"Invalid build path: {build_path}")

                # Construct build arguments
                build_args = {
                    'path': build_path,
                    'dockerfile': container['build']['dockerfile'],
                    'tag': container['container_name']  # Use container name as the tag
                }

                # Log the build arguments for debugging
                logger.debug(f"Build arguments: {build_args}")

                # Attempt to build the image
                client.images.build(**build_args)
                logger.info(f"Image for {container['container_name']} built successfully")
            except ValueError as ve:
                logger.error(f"Error building image for {container['container_name']}: {str(ve)}")
            except docker.errors.BuildError as be:
                logger.error(f"Docker build error for {container['container_name']}: {str(be)}")
            except Exception as e:
                logger.error(f"Unexpected error building image for {container['container_name']}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error checking image for {container['container_name']}: {str(e)}")

@app.on_event("startup")
async def startup_event():
    build_predefined_containers()

@app.post("/start")
async def start_container(container: ContainerRequest, api_key: str = Depends(verify_api_key)):
    try:
        container_instance = client.containers.run(
            container.image,
            name=container.name,
            detach=True,
            environment=container.environment,
            volumes=container.volumes,
            network=container.network,
            extra_hosts=container.extra_hosts
        )
        logger.info(f"Container {container.name} started successfully")
        return {"id": container_instance.id, "name": container.name, "status": "running"}
    except Exception as e:
        logger.error(f"Error starting container: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/stop/{container_name}")
async def stop_container(container_name: str, api_key: str = Depends(verify_api_key)):
    try:
        container = client.containers.get(container_name)
        container.stop()
        logger.info(f"Container {container_name} stopped successfully")
        return {"name": container_name, "status": "stopped"}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container {container_name} not found")
    except Exception as e:
        logger.error(f"Error stopping container: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/list")
async def list_containers(api_key: str = Depends(verify_api_key)):
    try:
        containers = client.containers.list()
        return [{"id": c.id, "name": c.name, "status": c.status} for c in containers]
    except Exception as e:
        logger.error(f"Error listing containers: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))