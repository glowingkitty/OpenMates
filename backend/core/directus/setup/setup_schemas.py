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
DIRECTUS_TOKEN = os.getenv('DIRECTUS_TOKEN')

# Print environment variables for debugging
print(f"Environment variables loaded.")
print(f"ADMIN_EMAIL: {'*****' if ADMIN_EMAIL else 'Not set'}")
print(f"ADMIN_PASSWORD: {'*****' if ADMIN_PASSWORD else 'Not set'}")
print(f"DIRECTUS_TOKEN: {'*****' if DIRECTUS_TOKEN else 'Not set'}")

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

def field_exists(token, collection_name, field_name):
    """Check if a field exists in a collection."""
    try:
        response = requests.get(
            f"{CMS_URL}/fields/{collection_name}/{field_name}",
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
        'textfield': 'text',  # Map textfield to text for longer content
        'text': 'text',
        'integer': 'integer',
        'boolean': 'boolean',
        'float': 'float',
        'decimal': 'decimal',
        'json': 'json',
        'uuid': 'uuid',
        'hash': 'hash',
        'array': 'json',  # Array fields should be stored as JSON
    }
    
    # Handle array notation (e.g. "string[]")
    if isinstance(type_name, str) and type_name.endswith('[]'):
        return 'json'
        
    return type_map.get(type_name, 'string')  # Default to string if type not found

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
        # Check if relation already exists
        try:
            relation_check = requests.get(
                f"{CMS_URL}/relations",
                params={
                    "filter[collection][_eq]": collection_name,
                    "filter[field][_eq]": field_name
                },
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if relation_check.status_code == 200:
                relation_data = relation_check.json().get('data', [])
                if relation_data and len(relation_data) > 0:
                    print(f"Relation already exists for {collection_name}.{field_name}")
                    return True
        except Exception as e:
            print(f"Error checking if relation exists: {str(e)}")
    
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

def create_or_update_field(token, collection_name, field_name, field_config, is_system_collection):
    """Creates a new field or updates an existing one (only for system collections)."""
    field_exists_flag = field_exists(token, collection_name, field_name)
    
    # Normalize the field type for Directus
    field_type = normalize_directus_type(field_config.get('type'))
    
    # For relation fields, ensure correct format
    special = field_config.get('special', [])
    if not isinstance(special, list):
        special = [special] if special else []
        
    is_relation = bool(field_config.get('relation'))
    if is_relation:
        field_type = "uuid"  # Relation fields should be uuid type
        if "uuid" not in special:
            special.append("uuid")

    # Prepare field data (common for create and update)
    field_data = {
        "type": field_type,
        "schema": {
            # Schema attributes are generally not updatable via PATCH on /fields
            # We only include them for POST
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

    if field_exists_flag:
        if is_system_collection:
            print(f"Updating existing field: {collection_name}.{field_name}")
            # Prepare data for PATCH (remove schema, add field name)
            patch_data = {
                "type": field_data["type"],
                "meta": field_data["meta"]
                # We generally cannot PATCH schema details like data_type, is_nullable etc.
                # Directus manages the underlying DB schema changes based on 'type' or relations.
            }
            try:
                response = requests.patch(
                    f"{CMS_URL}/fields/{collection_name}/{field_name}",
                    json=patch_data,
                    headers={"Authorization": f"Bearer {token}"}
                )
                if response.status_code >= 400:
                    print(f"Failed to update field: {response.status_code}")
                    print(f"Response body: {response.text}")
                else:
                    print(f"Successfully updated field {collection_name}.{field_name}")
            except Exception as e:
                print(f"Exception while updating field {field_name}: {str(e)}")
        else:
            # This case (field exists in a newly created non-system collection) shouldn't happen
            # for non-primary fields, but we log it just in case.
            print(f"Warning: Field {collection_name}.{field_name} already exists in a newly created collection. Skipping.")
        
        # Return True if it's a relation field, so it gets added to relations_to_create
        return is_relation

    else:
        print(f"Creating field: {collection_name}.{field_name}")
        # Prepare data for POST (include field name and full schema)
        post_data = {
            "field": field_name,
            "type": field_data["type"],
            "schema": field_data["schema"],
            "meta": field_data["meta"]
        }
        try:
            response = requests.post(
                f"{CMS_URL}/fields/{collection_name}",
                json=post_data,
                headers={"Authorization": f"Bearer {token}"}
            )
            if response.status_code >= 400:
                # Check if error is due to field already existing (race condition?)
                error_text = response.text
                if "already exists" in error_text:
                     print(f"Field {field_name} already exists (race condition?). This is OK, continuing...")
                else:
                    print(f"Failed to create field: {response.status_code}")
                    print(f"Response body: {response.text}")
            else:
                 print(f"Successfully created field {collection_name}.{field_name}")

        except Exception as e:
            print(f"Exception while creating field {field_name}: {str(e)}")
            
        # Return True if it's a relation field
        return is_relation


def create_collection(token, schema_file):
    """
    Create collection from schema file, or update fields/relations for existing system collections.
    Returns a tuple: (success: bool, newly_created: bool)
    """
    try:
        with open(schema_file, 'r') as f:
            schema = yaml.safe_load(f)
        
        # Get collection name from the first key in the schema
        collection_name = list(schema.keys())[0]
        is_system_collection = collection_name.startswith('directus_')
        
        # Check if collection already exists
        exists = collection_exists(token, collection_name)
        create_new = False
        
        # Handle collection existence
        if is_system_collection:
            if exists:
                print(f"System collection {collection_name} exists, will process fields/relations.")
            else:
                # This shouldn't happen for core system collections like directus_users
                print(f"Error: System collection {collection_name} expected but not found. Skipping.")
                return False, False 
        else:
            # For non-system collections, create if they don't exist
            if exists:
                print(f"Custom collection {collection_name} already exists. Skipping creation and field processing.")
                # We skip processing fields for existing custom collections to avoid overwriting user changes.
                return True, False # Successful (nothing to do), not newly created
            else:
                print(f"Creating new custom collection: {collection_name}")
                create_new = True
        
        collection = schema[collection_name]
        
        # Create the collection if needed (non-system collections only)
        if create_new:
            # --- Collection Creation Logic ---
            primary_field = None
            # Find the primary field defined in schema
            if collection.get('fields'):
                for field_name, field_config in collection.get('fields').items():
                    if field_config.get('primary'):
                        primary_field = {
                            "field": field_name,
                            "type": normalize_directus_type(field_config.get('type', 'uuid')),
                            "meta": { "hidden": False, "readonly": False, "interface": "input", "special": ["uuid"] },
                            "schema": { "is_primary_key": True, "has_auto_increment": False, "data_type": "uuid" }
                        }
                        break
            
            # If no primary field is explicitly defined, create a default UUID one
            if not primary_field:
                primary_field = {
                    "field": "id", "type": "uuid",
                    "meta": { "hidden": False, "readonly": False, "interface": "input", "special": ["uuid"] },
                    "schema": { "is_primary_key": True, "has_auto_increment": False, "data_type": "uuid" }
                }
            
            # Create collection with explicit primary key type
            collection_data = {
                "collection": collection_name,
                "meta": {
                    "note": collection.get('note', ''),
                    "display_template": collection.get('display_template')
                },
                "schema": { "name": collection_name },
                "fields": [primary_field] # Define primary key during creation
            }
            
            try:
                response = requests.post(
                    f"{CMS_URL}/collections",
                    json=collection_data,
                    headers={"Authorization": f"Bearer {token}"}
                )
                response.raise_for_status()
                print(f"Successfully created collection {collection_name}")
                time.sleep(1) # Wait briefly after collection creation
            except Exception as e:
                 print(f"Failed to create collection {collection_name}: {str(e)}")
                 if hasattr(e, 'response') and e.response is not None:
                     print(f'Response status code: {e.response.status_code}')
                     print(f'Response body: {e.response.text}')
                 return False, False # Failed to create

        # --- Field and Relation Processing ---
        # Process fields if:
        # 1. The collection is newly created (create_new is True)
        # 2. The collection is a system collection (is_system_collection is True)
        should_process_fields = create_new or is_system_collection

        if should_process_fields:
            print(f"Processing fields and relations for {collection_name} (Newly created: {create_new}, System: {is_system_collection})")
            relations_to_create = []
            
            if collection.get('fields'):
                for field_name, field_config in collection['fields'].items():
                    # Skip primary key fields (handled during collection creation or already exists)
                    if field_config.get('primary'):
                        continue
                    
                    # Create or update the field, and check if it's a relation
                    is_relation = create_or_update_field(
                        token, collection_name, field_name, field_config, is_system_collection
                    )
                    
                    # If it's a relation field, store it for later processing
                    if is_relation and field_config.get('relation'):
                         relations_to_create.append((field_name, field_config.get('relation')))

            # Wait before creating relations
            if relations_to_create:
                print(f"Waiting before creating {len(relations_to_create)} relations for {collection_name}...")
                time.sleep(2) # Increased wait time before relations
                
                # Create relations
                print(f"Creating relations for {collection_name}...")
                for field_name, relation_config in relations_to_create:
                    create_relation(token, collection_name, field_name, relation_config)
                    time.sleep(0.2) # Small delay between relation creations
        
        # If we reached here, the process for this collection was successful
        print(f"Collection {collection_name} processed successfully (Newly created: {create_new})")
        return True, create_new
        
    except Exception as e:
        print(f'Error processing collection {collection_name}: {str(e)}')
        if hasattr(e, 'response') and e.response is not None:
            print(f'Response status code: {e.response.status_code}')
            print(f'Response body: {e.response.text}')
        return False, False # Not successful, not newly created


def check_if_database_initialized(token):
    """Check if database is already initialized by checking if key collections exist."""
    core_collections = ['invite_codes', 'chats', 'users']
    existing_collections = 0
    
    try:
        # Get all collections
        response = requests.get(
            f"{CMS_URL}/collections",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code == 200:
            collections = response.json().get('data', [])
            collection_names = [c.get('collection') for c in collections]
            
            for core in core_collections:
                # Check for both 'users' and 'directus_users' etc.
                if core in collection_names or f"directus_{core}" in collection_names:
                    existing_collections += 1
            
            # If most core collections exist, database is likely initialized
            if existing_collections >= 2:
                print(f"Found {existing_collections}/{len(core_collections)} core collections - database appears initialized")
                return True
    except Exception as e:
        print(f"Error checking if database is initialized: {str(e)}")
    
    return False

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

def store_invite_code(token, invite_code, is_admin=False):
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
                "remaining_uses": 1,
                "is_admin": is_admin
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        
        print(f"Successfully stored invite code {invite_code} (Admin: {is_admin})")
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
        
        invite_codes_newly_created = False # Track if invite_codes was specifically created now
        
        # Check if schema files directory exists and list content
        if not os.path.exists(SCHEMAS_DIR):
            print(f"Schemas directory not found: {SCHEMAS_DIR}")
            # Attempt to find it in parent directories for debugging/robustness
            parent_dir = os.path.dirname(SCHEMAS_DIR)
            while parent_dir != '/' and not os.path.exists(SCHEMAS_DIR):
                 print(f"Checking parent directory: {parent_dir}")
                 if os.path.exists(parent_dir):
                     print(f"Parent directory exists: {parent_dir}")
                     print(f"Parent directory contents: {os.listdir(parent_dir)}")
                     # Check if schemas subdir exists here
                     potential_schemas_dir = os.path.join(parent_dir, 'schemas')
                     if os.path.exists(potential_schemas_dir):
                          print(f"Found potential schemas dir: {potential_schemas_dir}")
                          # Optionally, you could set SCHEMAS_DIR = potential_schemas_dir here
                          break # Found it, stop searching up
                 parent_dir = os.path.dirname(parent_dir)

            print("Continuing without importing schemas if directory still not found.")
        
        if os.path.exists(SCHEMAS_DIR):
            # Find schema files
            schema_files = glob.glob(os.path.join(SCHEMAS_DIR, '*.yml')) + glob.glob(os.path.join(SCHEMAS_DIR, '*.yaml'))
            
            if not schema_files:
                print(f"No schema files (*.yml or *.yaml) found in {SCHEMAS_DIR}")
                print(f"Directory contents: {os.listdir(SCHEMAS_DIR)}")
                print("Continuing without importing schemas.")
            else:
                print(f"Found {len(schema_files)} schema file(s): {[os.path.basename(f) for f in schema_files]}")
                
                # Sort schema files to ensure dependencies are created first
                # Put users and chats first since they're referenced by other collections
                def sort_key(file_path):
                    basename = os.path.basename(file_path).lower()
                    # Prioritize directus_users specifically
                    if 'directus_users' in basename or basename.startswith('users.'):
                        return 0  # First priority
                    elif 'chats' in basename:
                        return 1  # Second priority
                    # Add other priorities if needed
                    return 2  # Default priority
                
                schema_files.sort(key=sort_key)
                print(f"Processing schema files in order: {[os.path.basename(f) for f in schema_files]}")
                
                for schema_file in schema_files:
                    print(f"\n--- Processing schema file: {os.path.basename(schema_file)} ---")
                    collection_name_from_file = os.path.basename(schema_file).split('.')[0] # e.g., 'invite_codes' from 'invite_codes.yml'
                    success, newly_created = create_collection(token, schema_file)
                    if success and newly_created and collection_name_from_file == 'invite_codes':
                        invite_codes_newly_created = True
                    print(f"--- Finished processing: {os.path.basename(schema_file)} (Success: {success}) ---")


        # Only create an admin invite code if the 'invite_codes' collection
        # was newly created during this run (i.e., first setup).
        if invite_codes_newly_created:
            print("\nFirst startup detected (invite_codes collection created) - generating invite code for admin user...")
            invite_code = generate_invite_code()
            
            # Store as admin invite code
            if store_invite_code(token, invite_code, is_admin=True):
                print(f"\n==================================")
                print(f"IMPORTANT: Use this invite code to create your first admin user:")
                print(f"Admin Invite Code: {invite_code}")
                print(f"This user will be granted full server admin privileges.")
                print(f"==================================\n")
            else:
                print("Failed to store admin invite code")
        
        print('\nSchema setup complete')
        
    except Exception as e:
        print(f'Schema setup failed: {str(e)}')
        # Optionally re-raise or exit differently
        import traceback
        traceback.print_exc()
        exit(1)

if __name__ == "__main__":
    setup_schemas()