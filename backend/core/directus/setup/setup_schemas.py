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
            return False
        
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
                
                # Normalize the field type for Directus
                field_type = normalize_directus_type(field_config.get('type'))
                
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
                        "special": field_config.get('special'),
                        "required": bool(field_config.get('required'))
                    }
                }
                
                # Debug output to help identify issues
                print(f"Field data being sent: {field_data}")
                
                # Try the correct endpoint based on restore_models.py
                try:
                    print(f"Creating field using /fields/{collection_name} endpoint")
                    field_response = requests.post(
                        f"{CMS_URL}/fields/{collection_name}",
                        json=field_data,
                        headers={"Authorization": f"Bearer {token}"}
                    )
                    field_response.raise_for_status()
                    print(f"Successfully created field {field_name}")
                except Exception as e:
                    print(f"Failed to create field: {str(e)}")
                    # If there's a response object with more information, print it
                    if hasattr(e, 'response') and e.response is not None:
                        print(f"Response status code: {e.response.status_code}")
                        print(f"Response body: {e.response.text}")
                    raise
                
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
                    
                    try:
                        relation_response = requests.post(
                            f"{CMS_URL}/relations",
                            json=relation_data,
                            headers={"Authorization": f"Bearer {token}"}
                        )
                        relation_response.raise_for_status()
                    except Exception as e:
                        print(f"Warning: Failed to create relation: {str(e)}")
                        print("Continuing with schema setup...")
        
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

def store_cms_token(token):
    """Store CMS token for API access."""
    try:
        # Check if API Access role already exists
        roles_response = requests.get(
            f"{CMS_URL}/roles",
            headers={"Authorization": f"Bearer {token}"}
        )
        roles_response.raise_for_status()
        
        # Check if API role already exists
        api_role_exists = False
        role_id = None
        
        for role in roles_response.json().get('data', []):
            if role.get('name') == "API Access":
                api_role_exists = True
                role_id = role.get('id')
                print('API Access role already exists')
                break
        
        if not api_role_exists:
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
            print('Created API Access role')
        
        # Check if API user already exists
        users_response = requests.get(
            f"{CMS_URL}/users?filter[email][_eq]=api@openmates.internal",
            headers={"Authorization": f"Bearer {token}"}
        )
        users_response.raise_for_status()
        
        users = users_response.json().get('data', [])
        if users:
            user_id = users[0].get('id')
            print('API user already exists')
        else:
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
            print('Created API user')
        
        # Check if the API token already exists
        tokens_response = requests.get(
            f"{CMS_URL}/users/{user_id}/tokens",
            headers={"Authorization": f"Bearer {token}"}
        )
        tokens_response.raise_for_status()
        
        tokens = tokens_response.json().get('data', [])
        token_exists = any(t.get('token') == CMS_TOKEN for t in tokens)
        
        if not token_exists:
            # Create a static token for API access
            token_response = requests.post(
                f"{CMS_URL}/users/{user_id}/token",
                json={"token": CMS_TOKEN},
                headers={"Authorization": f"Bearer {token}"}
            )
            token_response.raise_for_status()
            print('Created CMS API token')
        else:
            print('CMS API token already exists')
        
        print('CMS API token setup completed successfully')
        return True
    except Exception as e:
        print(f'Error setting up CMS token: {str(e)}')
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
                
                for schema_file in schema_files:
                    if create_collection(token, schema_file):
                        collections_created = True
        
        # Store CMS token for API access
        store_cms_token(token)
        
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