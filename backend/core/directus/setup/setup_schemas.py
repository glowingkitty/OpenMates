import os
import time
import yaml
import requests
import glob
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(dotenv_path='/usr/src/app/.env')

# Configuration from environment variables
CMS_URL = 'http://cms:8055'
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
CMS_TOKEN = os.getenv('CMS_TOKEN')

# Schema directories
SCHEMAS_DIR = '/usr/src/app/backend/core/directus/schemas'

def wait_for_directus():
    """Wait until Directus is ready and responsive."""
    print('Waiting for Directus to be ready...')
    
    while True:
        try:
            response = requests.get(f"{CMS_URL}/server/health")
            if response.status_code == 200 and response.json().get('status') == 'ok':
                print('Directus is ready!')
                return
        except Exception as e:
            print(f'Waiting for Directus to be available... ({str(e)})')
        
        time.sleep(2)

def login():
    """Login to Directus and get access token."""
    try:
        response = requests.post(f"{CMS_URL}/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        response.raise_for_status()
        return response.json()['data']['access_token']
    except Exception as e:
        print(f'Login failed: {str(e)}')
        raise

def collection_exists(token, collection_name):
    """Check if a collection exists in Directus."""
    try:
        response = requests.get(
            f"{CMS_URL}/collections/{collection_name}",
            headers={"Authorization": f"Bearer {token}"}
        )
        return response.status_code == 200
    except Exception:
        return False

def map_type(type_name, length=None):
    """Map Directus types to SQL types."""
    type_map = {
        'string': 'varchar' + (f'({length})' if length else '(255)'),
        'text': 'text',
        'integer': 'integer',
        'boolean': 'boolean',
        'datetime': 'timestamp with time zone',
        'uuid': 'uuid'
    }
    return type_map.get(type_name, 'varchar(255)')

def create_collection(token, schema_file):
    """Create collection from schema file."""
    try:
        with open(schema_file, 'r') as f:
            schema = yaml.safe_load(f)
        
        # Get collection name from the first key in the schema
        collection_name = list(schema.keys())[0]
        
        # Check if collection already exists
        exists = collection_exists(token, collection_name)
        if exists:
            print(f"Collection {collection_name} already exists, skipping")
            return
        
        # Create collection
        print(f"Creating collection: {collection_name}")
        
        collection = schema[collection_name]
        
        # First create the collection
        response = requests.post(
            f"{CMS_URL}/collections",
            json={
                "collection": collection_name,
                "meta": {
                    "note": collection.get('note', ''),
                    "display_template": collection.get('display_template')
                },
                "schema": {
                    "name": collection_name
                }
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        
        # Then create fields
        if collection.get('fields'):
            for field_name, field_config in collection['fields'].items():
                # Skip primary key fields as they are created automatically
                if field_config.get('primary'):
                    continue
                
                print(f"Creating field: {collection_name}.{field_name}")
                
                field_data = {
                    "collection": collection_name,
                    "field": field_name,
                    "type": field_config.get('type'),
                    "meta": {
                        "note": field_config.get('note'),
                        "interface": field_config.get('interface'),
                        "options": field_config.get('options'),
                        "special": field_config.get('special'),
                        "required": bool(field_config.get('required'))
                    },
                    "schema": {
                        "name": field_name,
                        "table": collection_name,
                        "data_type": map_type(field_config.get('type'), field_config.get('length')),
                        "default_value": field_config.get('default'),
                        "is_nullable": field_config.get('nullable', True) is not False,
                        "is_unique": bool(field_config.get('unique'))
                    }
                }
                
                field_response = requests.post(
                    f"{CMS_URL}/fields",
                    json=field_data,
                    headers={"Authorization": f"Bearer {token}"}
                )
                field_response.raise_for_status()
                
                # If it's a relation field, set up the relation
                if field_config.get('relation'):
                    relation = field_config['relation']
                    relation_data = {
                        "collection": collection_name,
                        "field": field_name,
                        "related_collection": relation.get('collection'),
                        "meta": {
                            "one_field": relation.get('one_field'),
                            "junction_field": relation.get('junction_field'),
                            "many_field": relation.get('many_field'),
                            "one_collection": relation.get('one_collection'),
                            "one_allowed_collections": relation.get('one_allowed_collections'),
                            "one_deselect_action": relation.get('one_deselect_action', 'nullify'),
                            "junction_collection": relation.get('junction_collection')
                        }
                    }
                    
                    relation_response = requests.post(
                        f"{CMS_URL}/relations",
                        json=relation_data,
                        headers={"Authorization": f"Bearer {token}"}
                    )
                    relation_response.raise_for_status()
        
        print(f"Collection {collection_name} created successfully")
    except Exception as e:
        print(f'Error creating collection: {str(e)}')
        raise

def store_cms_token(token):
    """Store CMS token for API access."""
    try:
        # Create a role for API access
        role_response = requests.post(
            f"{CMS_URL}/roles",
            json={
                "name": "API Access",
                "admin_access": False,
                "app_access": False
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        role_response.raise_for_status()
        
        role_id = role_response.json()['data']['id']
        
        # Create a user for API access
        user_response = requests.post(
            f"{CMS_URL}/users",
            json={
                "email": "api@openmates.internal",
                "password": CMS_TOKEN[:32],  # Use part of the CMS token as password
                "role": role_id
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        user_response.raise_for_status()
        
        user_id = user_response.json()['data']['id']
        
        # Create a static token for API access
        token_response = requests.post(
            f"{CMS_URL}/users/{user_id}/token",
            json={"token": CMS_TOKEN},
            headers={"Authorization": f"Bearer {token}"}
        )
        token_response.raise_for_status()
        
        print('CMS API token stored successfully')
    except Exception as e:
        print(f'Error storing CMS token: {str(e)}')
        raise

def setup_schemas():
    """Main function to set up schemas."""
    wait_for_directus()

    try:
        token = login()
        print('Successfully logged in to Directus')
        
        # Check if schema files directory exists
        if os.path.exists(SCHEMAS_DIR):
            schema_files = glob.glob(os.path.join(SCHEMAS_DIR, '*.yml'))
            
            for schema_file in schema_files:
                create_collection(token, schema_file)
            
            # Store CMS token for API access
            store_cms_token(token)
            
            print('Schema setup complete')
        else:
            print(f"Schemas directory not found: {SCHEMAS_DIR}")
            exit(1)
    except Exception as e:
        print(f'Schema setup failed: {str(e)}')
        exit(1)

if __name__ == "__main__":
    setup_schemas()