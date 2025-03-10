import os
import time
import yaml
import random
import string
import requests
import glob
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration from environment variables
CMS_URL = 'http://cms:8055'
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
CMS_TOKEN = os.getenv('CMS_TOKEN')

# Print environment variables for debugging
print(f"Environment variables loaded:")
print(f"ADMIN_EMAIL: {ADMIN_EMAIL}")
print(f"ADMIN_PASSWORD: {'*****' if ADMIN_PASSWORD else 'Not set'}")
print(f"CMS_TOKEN: {'*****' if CMS_TOKEN else 'Not set'}")

# Schema directories - use environment variable or default
SCHEMAS_DIR = os.getenv('SCHEMAS_DIR', '/usr/src/app/schemas')

# Print information about the schemas directory
print(f"Using schemas from: {SCHEMAS_DIR}")
if os.path.exists(SCHEMAS_DIR):
    print(f"Directory contents: {os.listdir(SCHEMAS_DIR)}")
else:
    print(f"Directory not found: {SCHEMAS_DIR}")
    # Try to find schemas in parent directories
    for parent_dir in ['/usr/src/app', '/usr/src', '/usr']:
        print(f"Looking for schemas in {parent_dir}...")
        if os.path.exists(parent_dir):
            print(f"Found directory: {parent_dir}")
            print(f"Contents: {os.listdir(parent_dir)}")

def wait_for_directus():
    """Wait until Directus is ready and responsive."""
    print('Waiting for Directus to be ready...')
    
    # Maximum wait time: 2 minutes
    max_retries = 30
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Try direct connection first
            response = requests.get(f"{CMS_URL}")
            if response.status_code == 200:
                print('Directus is ready! (Main page accessible)')
                return
                
            # Try health check endpoint
            health_response = requests.get(f"{CMS_URL}/server/health")
            if health_response.status_code == 200:
                print('Directus is ready! (Health check passed)')
                return
                
            # Try ping endpoint as a last resort
            ping_response = requests.get(f"{CMS_URL}/server/ping")
            if ping_response.status_code == 200:
                print('Directus is ready! (Ping successful)')
                return
                
        except Exception as e:
            pass
        
        retry_count += 1
        if retry_count % 5 == 0:
            print(f'Waiting for Directus to be available... (attempt {retry_count}/{max_retries})')
        
        time.sleep(4)
    
    print("Directus did not become ready in the allowed time, but we'll try to continue anyway...")

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

def normalize_directus_type(type_name):
    """Convert schema types to valid Directus types."""
    type_map = {
        'datetime': 'dateTime',  # Note the capital T for Directus
        'date': 'date',
        'time': 'time',
        'string': 'string',
        'text': 'text',
        'integer': 'integer',
        'boolean': 'boolean',
        'float': 'float',
        'decimal': 'decimal',
        'json': 'json',
        'uuid': 'uuid',
        'hash': 'hash',
    }
    return type_map.get(type_name, type_name)

def check_field_type(token, collection_name, field_name):
    """Check the type of a field in a collection."""
    try:
        response = requests.get(
            f"{CMS_URL}/fields/{collection_name}/{field_name}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code == 200:
            data = response.json().get('data', {})
            return data.get('type'), data.get('schema', {}).get('data_type')
        
        return None, None
    except Exception:
        return None, None

def create_relation(token, collection_name, field_name, relation_config):
    """Create a relation between collections with improved error handling."""
    try:
        # Verify collections exist
        related_collection = relation_config.get('collection')
        related_field = relation_config.get('field', 'id')
        
        # Check if related collection exists
        if not collection_exists(token, related_collection):
            print(f"Error: Related collection '{related_collection}' does not exist.")
            
            # Special handling for 'users' - try directus_users instead
            if related_collection == 'users':
                print("Attempting to use 'directus_users' instead of 'users'...")
                relation_config['collection'] = 'directus_users'
                related_collection = 'directus_users'
                
                if not collection_exists(token, 'directus_users'):
                    print("Error: directus_users collection also not found.")
                    return False
            else:
                return False
                
        # Check field types for compatibility
        local_type, local_data_type = check_field_type(token, collection_name, field_name)
        related_type, related_data_type = check_field_type(token, related_collection, related_field)
        
        if local_type and related_type:
            print(f"Field types: {collection_name}.{field_name} ({local_type}/{local_data_type}) → " +
                  f"{related_collection}.{related_field} ({related_type}/{related_data_type})")
            
            # Ensure types are compatible (both should be uuid)
            if local_data_type != related_data_type:
                print(f"Warning: Field type mismatch. Relation may fail.")
                
                # Try to update field type if needed
                if (local_data_type == 'uuid' and related_data_type != 'uuid') or \
                   (local_data_type != 'uuid' and related_data_type == 'uuid'):
                    print(f"Attempting to fix incompatible data types...")
        
        # Prepare relation data with proper structure
        relation_data = {
            "collection": collection_name,
            "field": field_name,
            "related_collection": relation_config.get('collection')
        }
        
        # Add meta information if provided
        meta = {}
        
        # Add optional fields only if they are present in the config
        for field in ['one_field', 'junction_field', 'many_field', 'one_collection', 
                     'one_deselect_action', 'junction_collection']:
            if relation_config.get(field) is not None:
                meta[field] = relation_config.get(field)
                
        # Add one_allowed_collections as an array if provided
        if relation_config.get('one_allowed_collections'):
            meta['one_allowed_collections'] = relation_config.get('one_allowed_collections')
            
        # Only add meta if we have data
        if meta:
            relation_data['meta'] = meta

        print(f"Creating relation for {collection_name}.{field_name} -> {relation_config.get('collection')}")
        print(f"Relation data: {relation_data}")
        
        # Create the relation
        relation_response = requests.post(
            f"{CMS_URL}/relations",
            json=relation_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Better error handling
        if relation_response.status_code >= 400:
            print(f"Error creating relation: Status {relation_response.status_code}")
            print(f"Response body: {relation_response.text}")
            return False
            
        print(f"Successfully created relation for {collection_name}.{field_name}")
        return True
        
    except Exception as e:
        print(f"Exception creating relation: {str(e)}")
        if hasattr(e, 'response') and e.response:
            print(f"Response status: {e.response.status_code}")
            print(f"Response text: {e.response.text}")
        return False

def create_collection(token, schema_file):
    """Create collection from schema file."""
    try:
        with open(schema_file, 'r') as f:
            schema = yaml.safe_load(f)
        
        # Get collection name from the first key in the schema
        collection_name = list(schema.keys())[0]
        
        # Check if collection already exists
        exists = collection_exists(token, collection_name)
        create_new = False
        
        # For system collections like directus_users, we don't create them, just add fields
        if collection_name.startswith('directus_'):
            if exists:
                print(f"System collection {collection_name} exists, will add/update fields")
            else:
                print(f"System collection {collection_name} doesn't exist, skipping")
                return False
        else:
            # For non-system collections, create if they don't exist
            if exists:
                print(f"Collection {collection_name} already exists, will add/update fields")
            else:
                print(f"Creating new collection: {collection_name}")
                create_new = True
        
        collection = schema[collection_name]
        
        # Create the collection if needed (non-system collections only)
        if create_new:
            # Set explicit schema for uuid fields
            schema_fields = []
            primary_field = None
            
            # Find the primary field
            if collection.get('fields'):
                for field_name, field_config in collection.get('fields').items():
                    if field_config.get('primary'):
                        primary_field = {
                            "field": field_name,
                            "type": normalize_directus_type(field_config.get('type', 'uuid')),
                            "meta": {
                                "hidden": False,
                                "readonly": False,
                                "interface": "input",
                                "special": ["uuid"]
                            },
                            "schema": {
                                "is_primary_key": True,
                                "has_auto_increment": False,
                                "data_type": "uuid"
                            }
                        }
                        break
            
            # If no primary field is explicitly defined, create a default UUID one
            if not primary_field:
                primary_field = {
                    "field": "id",
                    "type": "uuid",
                    "meta": {
                        "hidden": False,
                        "readonly": False,
                        "interface": "input",
                        "special": ["uuid"]
                    },
                    "schema": {
                        "is_primary_key": True,
                        "has_auto_increment": False,
                        "data_type": "uuid"
                    }
                }
            
            # Create collection with explicit primary key type
            collection_data = {
                "collection": collection_name,
                "meta": {
                    "note": collection.get('note', ''),
                    "display_template": collection.get('display_template')
                },
                "schema": {
                    "name": collection_name
                },
                "fields": [primary_field]
            }
            
            response = requests.post(
                f"{CMS_URL}/collections",
                json=collection_data,
                headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()
            
            # Wait to ensure collection is created properly
            time.sleep(1)
        
        # Store relations to create after all fields are created
        relations_to_create = []
        
        # Then create or update fields
        if collection.get('fields'):
            for field_name, field_config in collection['fields'].items():
                # Skip primary key fields as they are created automatically
                if field_config.get('primary'):
                    continue
                
                # Check if field already exists
                field_exists = False
                try:
                    field_check = requests.get(
                        f"{CMS_URL}/fields/{collection_name}/{field_name}",
                        headers={"Authorization": f"Bearer {token}"}
                    )
                    field_exists = field_check.status_code == 200
                except Exception:
                    field_exists = False
                
                action = "Updating" if field_exists else "Creating"
                print(f"{action} field: {collection_name}.{field_name}")
                
                # Normalize the field type for Directus
                field_type = normalize_directus_type(field_config.get('type'))
                
                # For relation fields, ensure correct format
                special = field_config.get('special', [])
                if not isinstance(special, list):
                    special = [special] if special else []
                    
                if field_config.get('relation'):
                    field_type = "uuid"  # Relation fields should be uuid type
                    if "uuid" not in special:
                        special.append("uuid")
                    # Store relation for later creation
                    relations_to_create.append((field_name, field_config.get('relation')))
                
                # Prepare field data
                field_data = {
                    "field": field_name,
                    "type": field_type,
                    "schema": {
                        "name": field_name,
                        "table": collection_name,
                        "data_type": map_type(field_config.get('type'), field_config.get('length')),
                        "default_value": field_config.get('default'),
                        "is_nullable": field_config.get('nullable', True) is not False,
                        "is_unique": bool(field_config.get('unique'))
                    },
                    "meta": {
                        "note": field_config.get('note'),
                        "interface": field_config.get('interface'),
                        "options": field_config.get('options'),
                        "special": special,
                        "required": bool(field_config.get('required'))
                    }
                }
                
                # Try the correct endpoint based on restore_models.py
                try:
                    field_response = requests.post(
                        f"{CMS_URL}/fields/{collection_name}",
                        json=field_data,
                        headers={"Authorization": f"Bearer {token}"}
                    )
                    field_response.raise_for_status()
                except Exception as e:
                    print(f"Failed to create field: {str(e)}")
                    if hasattr(e, 'response') and e.response is not None:
                        print(f"Response status code: {e.response.status_code}")
                        print(f"Response body: {e.response.text}")
                    raise
        
        # Wait before creating relations to ensure all fields are ready
        time.sleep(1)
        
        # Create relations after all fields are created
        for field_name, relation_config in relations_to_create:
            # Add a small delay between relation creations
            time.sleep(0.5)
            create_relation(token, collection_name, field_name, relation_config)
        
        print(f"Collection {collection_name} created successfully")
        return True
        
    except Exception as e:
        print(f'Error creating collection: {str(e)}')
        if hasattr(e, 'response') and e.response is not None:
            print(f'Response status code: {e.response.status_code}')
            print(f'Response body: {e.response.text}')
        raise

def generate_invite_code():
    """Generate an invite code in the format XXXX-XXXX-XXXX using only numbers."""
    digits = string.digits  # Use only digits 0-9
    
    # Generate 3 groups of 4 random digits
    part1 = ''.join(random.choices(digits, k=4))
    part2 = ''.join(random.choices(digits, k=4))
    part3 = ''.join(random.choices(digits, k=4))
    
    # Format as XXXX-XXXX-XXXX
    invite_code = f"{part1}-{part2}-{part3}"
    print(f"Generated invite code: {invite_code}")
    
    return invite_code

def store_invite_code(token, invite_code):
    """Store the generated invite code in the database."""
    try:
        # Check if invite_codes collection exists
        if not collection_exists(token, 'invite_codes'):
            print("Collection invite_codes does not exist. Please ensure it's defined in schema files.")
            return False
        
        # Insert the invite code into the database - without dates
        response = requests.post(
            f"{CMS_URL}/items/invite_codes",
            json={
                "code": invite_code,
                "remaining_uses": 1
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        
        print(f"Successfully stored invite code {invite_code}")
        return True
    except Exception as e:
        print(f"Error storing invite code: {str(e)}")
        return False

def setup_schemas():
    """Main function to set up schemas."""
    wait_for_directus()

    try:
        token = login()
        print('Successfully logged in to Directus')
        
        # Check if schema files directory exists and list content
        if not os.path.exists(SCHEMAS_DIR):
            print(f"Schemas directory not found: {SCHEMAS_DIR}")
            print("Checking parent directory...")
            parent_dir = os.path.dirname(SCHEMAS_DIR)
            if os.path.exists(parent_dir):
                print(f"Parent directory exists: {parent_dir}")
                print(f"Parent directory contents: {os.listdir(parent_dir)}")
            print("Continuing without importing schemas.")
        else:
            # Find schema files
            schema_files = glob.glob(os.path.join(SCHEMAS_DIR, '*.yml')) + glob.glob(os.path.join(SCHEMAS_DIR, '*.yaml'))
            
            if not schema_files:
                print(f"No schema files (*.yml or *.yaml) found in {SCHEMAS_DIR}")
                print(f"Directory contents: {os.listdir(SCHEMAS_DIR)}")
                print("Continuing without importing schemas.")
            else:
                print(f"Found {len(schema_files)} schema file(s): {[os.path.basename(f) for f in schema_files]}")
                collections_created = False
                
                # Sort schema files to ensure dependencies are created first
                # Put users and chats first since they're referenced by other collections
                def sort_key(file_path):
                    basename = os.path.basename(file_path).lower()
                    if 'directus_users' in basename or 'users' in basename:
                        return 0  # First priority
                    elif 'chats' in basename:
                        return 1  # Second priority
                    return 2  # Default priority
                
                schema_files.sort(key=sort_key)
                print(f"Processing schema files in order: {[os.path.basename(f) for f in schema_files]}")
                
                for schema_file in schema_files:
                    if create_collection(token, schema_file):
                        collections_created = True

        # Generate and store invite code if new collections were created
        # or if the invite_codes collection exists but has no active codes
        invite_code_needed = collections_created
        
        if collection_exists(token, 'invite_codes'):
            # Check if there are any active invite codes
            try:
                response = requests.get(
                    f"{CMS_URL}/items/invite_codes?filter[remaining_uses][_gt]=0",
                    headers={"Authorization": f"Bearer {token}"}
                )
                
                if response.status_code == 200:
                    active_codes = response.json().get('data', [])
                    if not active_codes:
                        invite_code_needed = True
                else:
                    invite_code_needed = True
            except Exception as e:
                print(f"Error checking active invite codes: {str(e)}")
                invite_code_needed = True
        
        if invite_code_needed:
            print("Generating invite code for first user...")
            invite_code = generate_invite_code()
            if store_invite_code(token, invite_code):
                print(f"\n==================================")
                print(f"IMPORTANT: Use this invite code to create your first admin user:")
                print(f"Invite Code: {invite_code}")
                print(f"==================================\n")
        else:
            print("No new collections created and active invite codes exist")
        
        print('Schema setup complete')
        
    except Exception as e:
        print(f'Schema setup failed: {str(e)}')
        exit(1)

if __name__ == "__main__":
    setup_schemas()