import os
import docker
import sys
import logging
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from typing import List, Optional, Dict
import json

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
json_path = os.path.join(server_dir, 'apps', 'app_docker_containers.json')

# Load app docker container configs
try:
    with open(json_path, 'r') as f:
        app_docker_containers = json.load(f)
    logger.info(f"Successfully loaded app_docker_containers.json from {json_path}")
except FileNotFoundError:
    logger.error(f"app_docker_containers.json not found at {json_path}")
    logger.error("Exiting container manager...")
    sys.exit(1)
except json.JSONDecodeError:
    logger.error(f"Error decoding app_docker_containers.json at {json_path}")
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
    for container in app_docker_containers:
        try:
            # Try to get the image
            client.images.get(container['image'])
            logger.info(f"Image {container['image']} already exists")
        except docker.errors.ImageNotFound:
            logger.info(f"Image {container['image']} not found. Attempting to build...")
            try:
                # Construct the build path
                build_path = os.path.join(server_dir, os.path.dirname(container['dockerfile']))
                if not os.path.isdir(build_path):
                    raise ValueError(f"Invalid build path: {build_path}")
                
                # Construct build arguments
                build_args = {
                    'path': build_path,
                    'dockerfile': os.path.basename(container['dockerfile']),
                    'tag': container['image']
                }
                
                # Log the build arguments for debugging
                logger.debug(f"Build arguments: {build_args}")
                
                # Attempt to build the image
                client.images.build(**build_args)
                logger.info(f"Image {container['image']} built successfully")
            except ValueError as ve:
                logger.error(f"Error building image {container['image']}: {str(ve)}")
            except docker.errors.BuildError as be:
                logger.error(f"Docker build error for {container['image']}: {str(be)}")
            except Exception as e:
                logger.error(f"Unexpected error building image {container['image']}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error checking image {container['image']}: {str(e)}")

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