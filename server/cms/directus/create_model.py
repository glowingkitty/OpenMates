# OLD SCRIPT
import logging
import requests
import os
import json
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def load_model_definitions() -> Dict[str, Any]:
    """
    Load all model definitions from JSON files in the /import_models folder
    and move processed files to /import_models/done subfolder only after successful processing

    Returns:
        Dict[str, Any]: Dictionary with collection names as keys and their definitions as values
    """
    logger.debug("Loading model definitions from import_models folder")
    models = {}

    # Define paths - Update to use absolute path
    script_dir = Path(__file__).parent  # Get the directory where the script is located
    import_path = script_dir / "import_models"
    done_path = import_path / "done"

    logger.debug(f"Looking for model definitions in: {import_path}")

    # Create directories if they don't exist
    if not import_path.exists():
        logger.warning(f"import_models folder not found at {import_path}. Creating it...")
        import_path.mkdir(exist_ok=True)

    if not done_path.exists():
        logger.debug("Creating 'done' subfolder...")
        done_path.mkdir(exist_ok=True)

    # Process JSON files
    for json_file in import_path.glob("*.json"):
        # Skip files in 'done' directory
        if 'done' in json_file.parts:
            continue

        try:
            # First try to load and validate the JSON
            with open(json_file, 'r') as f:
                model_def = json.load(f)
                collection_name = json_file.stem

                # Basic validation that the model definition has required fields
                if not isinstance(model_def, dict) or 'fields' not in model_def:
                    logger.error(f"Invalid model definition in {json_file}: Missing 'fields' key")
                    continue

                # If we get here, the file was processed successfully
                models[collection_name] = model_def
                logger.debug(f"Successfully loaded model definition for {collection_name}")

                # Move to done folder only after successful processing
                target_path = done_path / json_file.name
                json_file.rename(target_path)
                logger.info(f"Moved {json_file.name} to done folder after successful processing")

        except json.JSONDecodeError as je:
            logger.error(f"Invalid JSON in {json_file}: {str(je)}")
        except Exception as e:
            logger.error(f"Failed to process {json_file}: {str(e)}")

    return models

def get_field_icon(field_type: str, field_name: str) -> str:
    """
    Get appropriate icon for field based on its type and name
    """
    # Common field type mappings
    type_icons = {
        "string": "text_fields",
        "text": "notes",
        "boolean": "toggle_on",
        "integer": "numbers",
        "hash": "password",
        "relation": "link"
    }

    # Special field name mappings
    name_icons = {
        "email": "email",
        "password": "lock",
        "api_token": "key",
        "username": "account_circle",
        "profile_image": "image",
        "balance_credits": "account_balance",
        "goals": "flag",
        "likes": "thumb_up",
        "dislikes": "thumb_down",
        "teams": "group",
        "projects": "folder"
    }

    # First check if we have a specific icon for this field name
    if field_name in name_icons:
        return name_icons[field_name]

    # Otherwise use the type-based icon or default
    return type_icons.get(field_type, "label")

class DirectusSchemaManager:
    def __init__(self, base_url: str, access_token: str):
        """
        Initialize the DirectusSchemaManager

        Args:
            base_url: Base URL of your Directus instance
            access_token: Admin access token for authentication
        """
        self.base_url = base_url.rstrip('/')
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

    def create_collection(self, collection_name: str, fields: list) -> None:
        """
        Create a new collection in Directus with UUID as primary key

        Args:
            collection_name: Name of the collection
            fields: List of field definitions
        """
        url = f"{self.base_url}/collections"

        # Define UUID primary key field
        collection_data = {
            "collection": collection_name,
            "meta": {
                "icon": "account_circle",
                "note": f"{collection_name} collection",
                "display_template": "{{name}}"
            },
            "schema": {
                "name": collection_name
            },
            "fields": [
                {
                    "field": "id",
                    "type": "uuid",
                    "meta": {
                        "hidden": True,
                        "readonly": True,
                        "interface": "input",
                        "special": ["uuid"]
                    },
                    "schema": {
                        "is_primary_key": True,
                        "has_auto_increment": False,
                        "data_type": "uuid",
                        "default_value": None
                    }
                }
            ]
        }

        try:
            logger.info(f"Creating collection: {collection_name} with UUID primary key")
            response = requests.post(url, json=collection_data, headers=self.headers)
            response.raise_for_status()

            # Create fields after collection is created
            for field in fields:
                if field['field'] != 'id':  # Skip the id field as we've already created it
                    logger.debug(f"Processing field: {field['field']}")
                    self.create_field(collection_name, field)
                else:
                    logger.debug("Skipping 'id' field as it's already created with UUID type")

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create collection: {str(e)}")
            raise

    def create_field(self, collection_name: str, field_data: Dict[str, Any]) -> None:
        """
        Create a new field in a collection

        Args:
            collection_name: Name of the collection
            field_data: Field definition
        """
        url = f"{self.base_url}/fields/{collection_name}"

        try:
            logger.info(f"Creating field {field_data['field']} in collection {collection_name}")
            response = requests.post(url, json=field_data, headers=self.headers)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create field: {str(e)}")
            raise

# TODO add relation fields to the schema
# TODO update api endpoints/other scripts and replace stripe with directus

def main():
    """Main function to create collections in Directus"""
    # Load configuration from environment variables
    directus_url = os.getenv("DIRECTUS_URL", "http://localhost:1337")
    admin_token = os.getenv("DIRECTUS_ADMIN_TOKEN")

    if not admin_token:
        logger.error("DIRECTUS_ADMIN_TOKEN environment variable is not set")
        raise ValueError("Missing DIRECTUS_ADMIN_TOKEN")

    try:
        # Initialize the schema manager
        schema_manager = DirectusSchemaManager(directus_url, admin_token)

        # Load model definitions from JSON files
        models = load_model_definitions()

        if not models:
            logger.warning("No model definitions found in import_models folder")
            return

        # Create collections from loaded models
        for collection_name, model_def in models.items():
            logger.info(f"Creating collection: {collection_name}")
            fields = model_def.get("fields", [])
            # Add icons to fields
            for field in fields:
                if "meta" not in field:
                    field["meta"] = {}
                field["meta"]["icon"] = get_field_icon(field["type"], field["field"])
            schema_manager.create_collection(collection_name, fields)

        logger.info("Successfully created all collections in Directus")

    except Exception as e:
        logger.error(f"Failed to create schema: {str(e)}")
        raise

if __name__ == "__main__":
    main()