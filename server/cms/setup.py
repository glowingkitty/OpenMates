import sys
import os
import re
import requests
import time
import logging
from server.api.models.mates import Mate
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')

STRAPI_URL = os.getenv('STRAPI_URL')
STRAPI_TOKEN = os.getenv('STRAPI_TOKEN')

# Define the content models
CONTENT_MODELS = [Mate]

def check_strapi_online():
    # Check if Strapi is online
    try:
        while True:
            try:
                response = requests.get(STRAPI_URL)
                if response.status_code == 200:
                    logging.info("Strapi is online.")
                    return
                else:
                    logging.info(response.status_code)
            except requests.exceptions.ConnectionError:
                logging.info("Strapi is not online. Retrying in 5 seconds...")
                time.sleep(5)
    except KeyboardInterrupt:
        logging.info("Interrupted by user. Exiting...")
        exit(0)

def check_content_models():
    # Check if the content models exist
    try:
        for model in CONTENT_MODELS:
            model_name = model.__name__
            response = requests.get(f"{STRAPI_URL}/api/content-type-builder/content-types/{model_name}")
            if response.status_code != 200:
                logging.info(f"Content model {model_name} does not exist. Creating...")
                create_content_model(model)
    except KeyboardInterrupt:
        logging.info("Interrupted by user. Exiting...")
        exit(0)

def convert_model_to_strapi(model):
    fields = []
    for name, field in model.__annotations__.items():
        strapi_field = {
            "name": name,
            "type": str(field).lower(),
            "required": True,
            "unique": False
        }
        fields.append(strapi_field)
    return fields


def get_all_content_types():
    # Get all existing content types
    try:
        headers = {"Authorization": f"Bearer {STRAPI_TOKEN}"}
        response = requests.get(f"{STRAPI_URL}/api/content-type-builder/content-types", headers=headers)
        if response.status_code == 200:
            logging.info("Successfully fetched all content types.")
            return response.json()
        else:
            logging.info("Failed to fetch content types.")
            logging.info(response.json())
    except Exception as e:
        logging.info(f"An error occurred: {e}")
    except KeyboardInterrupt:
        logging.info("Interrupted by user. Exiting...")
        exit(0)


def create_content_model(model):
    # Here you would use the Strapi Content Type Builder API to create the content model
    # The exact request depends on the specifics of your content model
    try:
        model_name = model.__name__
        fields = convert_model_to_strapi(model)
        headers = {"Authorization": f"Bearer {STRAPI_TOKEN}"}
        response = requests.post(f"{STRAPI_URL}/api/content-type-builder/content-types", headers=headers, json={"name": model_name, "fields": fields})
        if response.status_code == 200:
            logging.info(f"Content model {model_name} created successfully.")
        else:
            logging.info(f"Failed to create content model {model_name}.")
            logging.info(response.json())
            
    except Exception as e:
        logging.info(f"An error occurred: {e}")

    except KeyboardInterrupt:
        logging.info("Interrupted by user. Exiting...")
        exit(0)

if __name__ == "__main__":
    check_strapi_online()
    get_all_content_types()
    check_content_models()