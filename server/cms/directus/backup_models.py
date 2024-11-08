import logging
import requests
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class DirectusBackup:
    def __init__(self, base_url: str, access_token: str):
        """
        Initialize DirectusBackup with API credentials

        Args:
            base_url: Directus instance URL
            access_token: Admin access token
        """
        self.base_url = base_url.rstrip('/')
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

    def get_collections(self) -> list:
        """Fetch all collections from Directus"""
        try:
            url = f"{self.base_url}/collections"
            logger.debug(f"Fetching collections from {url}")
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()['data']
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch collections: {str(e)}")
            raise

    def get_fields(self, collection_name: str) -> list:
        """Fetch all fields for a specific collection"""
        try:
            url = f"{self.base_url}/fields/{collection_name}"
            logger.debug(f"Fetching fields for collection {collection_name}")
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()['data']
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch fields for {collection_name}: {str(e)}")
            raise

    def backup_models(self, backup_dir: Path) -> None:
        """
        Backup all collections and their fields to JSON files

        Args:
            backup_dir: Directory to store backup files
        """
        # Create backup directory with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / timestamp
        backup_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Starting backup to {backup_path}")

        collections = self.get_collections()
        for collection in collections:
            collection_name = collection['collection']

            # Skip system collections
            if collection_name.startswith('directus_'):
                logger.debug(f"Skipping system collection: {collection_name}")
                continue

            try:
                fields = self.get_fields(collection_name)

                model_def = {
                    'collection': collection['collection'],
                    'meta': collection.get('meta', {}),
                    'schema': collection.get('schema', {}),
                    'fields': fields
                }

                # Save to JSON file
                backup_file = backup_path / f"{collection_name}.json"
                with open(backup_file, 'w') as f:
                    json.dump(model_def, f, indent=2)
                logger.info(f"Backed up {collection_name} to {backup_file}")

            except Exception as e:
                logger.error(f"Failed to backup {collection_name}: {str(e)}")

def main():
    """Main function to backup Directus collections"""
    directus_url = os.getenv("DIRECTUS_URL", "http://localhost:1337")
    admin_token = os.getenv("DIRECTUS_ADMIN_TOKEN")

    if not admin_token:
        logger.error("DIRECTUS_ADMIN_TOKEN environment variable is not set")
        raise ValueError("Missing DIRECTUS_ADMIN_TOKEN")

    try:
        # Initialize backup manager
        backup_manager = DirectusBackup(directus_url, admin_token)

        # Define backup directory
        script_dir = Path(__file__).parent
        backup_dir = script_dir / "model_backups"

        # Perform backup
        backup_manager.backup_models(backup_dir)
        logger.info("Backup completed successfully")

    except Exception as e:
        logger.error(f"Backup failed: {str(e)}")
        raise

if __name__ == "__main__":
    main()