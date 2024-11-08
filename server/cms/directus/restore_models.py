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

class DirectusRestore:
    def __init__(self, base_url: str, access_token: str):
        """
        Initialize DirectusRestore with API credentials

        Args:
            base_url: Directus instance URL
            access_token: Admin access token
        """
        self.base_url = base_url.rstrip('/')
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

    def collection_exists(self, collection_name: str) -> bool:
        """
        Check if a collection exists

        Args:
            collection_name: Name of the collection to check
        Returns:
            bool: True if collection exists, False otherwise
        """
        try:
            url = f"{self.base_url}/collections/{collection_name}"
            logger.debug(f"Checking if collection exists: {collection_name}")
            response = requests.get(url, headers=self.headers)
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to check collection existence: {str(e)}")
            return False

    def delete_collection(self, collection_name: str) -> None:
        """
        Delete a collection

        Args:
            collection_name: Name of the collection to delete
        """
        try:
            url = f"{self.base_url}/collections/{collection_name}"
            logger.info(f"Deleting collection: {collection_name}")
            response = requests.delete(url, headers=self.headers)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to delete collection: {str(e)}")
            raise

    def create_collection(self, collection_data: Dict[str, Any]) -> None:
        """
        Create a collection from backup data

        Args:
            collection_data: Dictionary containing collection configuration
        """
        try:
            collection_name = collection_data['collection']

            # Find the ID field configuration from backup
            id_field = next((field for field in collection_data['fields'] if field['field'] == 'id'), None)
            if not id_field:
                logger.error(f"No ID field configuration found for collection {collection_name}")
                raise ValueError(f"Missing ID field configuration for {collection_name}")

            # Check if collection exists and delete if it does
            if self.collection_exists(collection_name):
                logger.info(f"Collection {collection_name} already exists, deleting it first")
                self.delete_collection(collection_name)

            url = f"{self.base_url}/collections"
            logger.debug(f"Creating collection: {collection_name}")

            # Prepare collection data with ID field from backup
            collection_data_with_id = {
                "collection": collection_name,
                "meta": collection_data.get('meta', {}),
                "schema": collection_data.get('schema', {}),
                "fields": [
                    {
                        "field": "id",
                        "type": id_field['type'],
                        "meta": id_field.get('meta', {
                            "hidden": True,
                            "readonly": True,
                            "interface": "input",
                            "special": [id_field['type']]
                        }),
                        "schema": id_field.get('schema', {
                            "is_primary_key": True,
                            "has_auto_increment": False,
                            "data_type": id_field['type'],
                            "default_value": None
                        })
                    }
                ]
            }

            # Create the collection with proper ID field
            response = requests.post(url, json=collection_data_with_id, headers=self.headers)
            response.raise_for_status()

            # Create remaining fields after collection is created
            for field in collection_data['fields']:
                if field['field'] != 'id':  # Skip id field as it's already created
                    field_payload = {
                        "collection": field['collection'],
                        "field": field['field'],
                        "type": field['type'],
                        "schema": field['schema'],
                        "meta": field.get('meta', {})
                    }
                    self.create_field(collection_name, field_payload)

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create collection: {str(e)}")
            raise

    def create_field(self, collection_name: str, field_data: Dict[str, Any]) -> None:
        """Create a field in a collection"""
        try:
            url = f"{self.base_url}/fields/{collection_name}"
            logger.debug(f"Creating field {field_data['field']} in {collection_name}")
            response = requests.post(url, json=field_data, headers=self.headers)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create field: {str(e)}")
            raise

    def restore_from_backup(self, backup_path: Path) -> None:
        """
        Restore collections from backup files

        Args:
            backup_path: Path to backup directory
        """
        logger.info(f"Starting restore from {backup_path}")

        if not backup_path.exists():
            logger.error(f"Backup path does not exist: {backup_path}")
            raise FileNotFoundError(f"Backup directory not found: {backup_path}")

        for json_file in backup_path.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    collection_data = json.load(f)
                    logger.info(f"Restoring collection from {json_file.name}")
                    self.create_collection(collection_data)
            except json.JSONDecodeError as je:
                logger.error(f"Invalid JSON in {json_file}: {str(je)}")
            except Exception as e:
                logger.error(f"Failed to restore {json_file.name}: {str(e)}")

def main():
    """Main function to restore Directus collections"""
    directus_url = os.getenv("DIRECTUS_URL", "http://localhost:1337")
    admin_token = os.getenv("DIRECTUS_ADMIN_TOKEN")

    if not admin_token:
        logger.error("DIRECTUS_ADMIN_TOKEN environment variable is not set")
        raise ValueError("Missing DIRECTUS_ADMIN_TOKEN")

    try:
        # Initialize restore manager
        restore_manager = DirectusRestore(directus_url, admin_token)

        # Get backup directory path
        script_dir = Path(__file__).parent
        backup_dir = script_dir / "model_backups"

        # Let user select which backup to restore
        backups = sorted([d for d in backup_dir.iterdir() if d.is_dir()])
        if not backups:
            logger.error("No backups found")
            return

        print("\nAvailable backups:")
        for i, backup in enumerate(backups):
            print(f"{i+1}. {backup.name}")

        selection = int(input("\nSelect backup to restore (enter number): ")) - 1
        if 0 <= selection < len(backups):
            selected_backup = backups[selection]
            logger.info(f"Selected backup: {selected_backup}")
            restore_manager.restore_from_backup(selected_backup)
            logger.info("Restore completed successfully")
        else:
            logger.error("Invalid selection")

    except Exception as e:
        logger.error(f"Restore failed: {str(e)}")
        raise

if __name__ == "__main__":
    main()