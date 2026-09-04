import os
import time
import yaml
import secrets
import requests
import glob
import hashlib
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration from environment variables
CMS_URL = 'http://cms:8055'
ADMIN_EMAIL = os.getenv('DATABASE_ADMIN_EMAIL')
ADMIN_PASSWORD = os.getenv('DATABASE_ADMIN_PASSWORD')
DIRECTUS_TOKEN = os.getenv('DIRECTUS_TOKEN')
INTERNAL_API_SHARED_TOKEN = os.getenv('INTERNAL_API_SHARED_TOKEN')

# Print environment variables for debugging
print("Environment variables loaded.")
print(f"ADMIN_EMAIL: {'*****' if ADMIN_EMAIL else 'Not set'}")
print(f"ADMIN_PASSWORD: {'*****' if ADMIN_PASSWORD else 'Not set'}")
print(f"DIRECTUS_TOKEN: {'*****' if DIRECTUS_TOKEN else 'Not set'}")

# Schema directories - use environment variable or default
SCHEMAS_DIR = os.getenv('SCHEMAS_DIR', '/usr/src/app/schemas')
CHAT_RECOVERY_MIGRATION_PATH = os.getenv(
    'CHAT_RECOVERY_MIGRATION_PATH',
    '/usr/src/app/migrations/migrate_chat_recovery_unique_indexes.sql',
)
CHAT_RECOVERY_INDEXES = (
    'chat_turn_preflights_owner_chat_turn_uq',
    'chat_turn_preflights_user_message_uq',
    'chat_turn_preflights_task_uq',
    'chat_turn_preflights_billing_uq',
    'chat_inference_outbox_preflight_uq',
    'chat_inference_outbox_task_uq',
    'chat_inference_outbox_billing_uq',
    'chat_recovery_jobs_owner_chat_turn_uq',
    'chat_recovery_jobs_preflight_uq',
    'chat_recovery_jobs_task_uq',
    'chat_recovery_jobs_assistant_message_uq',
)
STORAGE_REPLICATION_MIGRATION_PATH = os.getenv(
    'STORAGE_REPLICATION_MIGRATION_PATH',
    '/usr/src/app/migrations/migrate_storage_replication_indexes.sql',
)
STORAGE_REPLICATION_INDEXES = (
    'storage_replication_jobs_identity_uq',
    'storage_replication_jobs_due_idx',
    'storage_deletion_tombstones_identity_uq',
    'storage_deletion_tombstones_due_idx',
    'storage_region_health_region_uq',
)
WORKFLOW_RUNTIME_MIGRATION_PATH = os.getenv(
    'WORKFLOW_RUNTIME_MIGRATION_PATH',
    '/usr/src/app/migrations/migrate_workflow_runtime_indexes.sql',
)
WORKFLOW_RUNTIME_INDEXES = (
    'workflow_triggers_due_claim_idx',
    'workflow_triggers_due_owner_idx',
    'workflow_versions_version_id_uq',
    'workflow_runs_acceptance_identity_uq',
    'workflow_event_receipts_trigger_event_uq',
    'workflow_template_projections_workflow_uq',
    'workflow_input_events_session_event_uq',
    'workflow_input_sessions_owner_updated_idx',
    'workflow_input_mutations_session_created_idx',
    'workflow_assistant_proposals_proposal_id_uq',
    'workflow_assistant_proposals_pending_expiry_idx',
)
USER_TASK_MIGRATION_PATH = os.getenv(
    'USER_TASK_MIGRATION_PATH',
    '/usr/src/app/migrations/migrate_user_task_indexes.sql',
)
USER_TASK_INDEXES = (
    'user_tasks_owner_status_position_idx',
    'user_tasks_owner_priority_idx',
    'user_tasks_team_admission_idx',
    'user_tasks_ai_admission_idx',
    'user_tasks_owner_completed_idx',
    'user_tasks_due_ai_idx',
    'user_tasks_owner_chat_idx',
    'user_tasks_project_hashes_gin_idx',
    'user_tasks_label_hashes_gin_idx',
    'user_task_key_wrappers_task_owner_idx',
    'user_task_activity_task_entry_uq',
    'user_task_activity_personal_created_idx',
    'user_task_activity_team_created_idx',
    'user_task_archives_owner_archived_idx',
)
USER_WORK_CONTROL_MIGRATION_PATH = os.getenv(
    'USER_WORK_CONTROL_MIGRATION_PATH',
    '/usr/src/app/migrations/migrate_user_work_control_indexes.sql',
)
USER_WORK_CONTROL_INDEXES = ('user_work_dependencies_source_target_uq',)
USAGE_OVERVIEW_MIGRATION_PATH = os.getenv(
    'USAGE_OVERVIEW_MIGRATION_PATH',
    '/usr/src/app/migrations/migrate_usage_overview_indexes.sql',
)
USAGE_OVERVIEW_INDEXES = (
    'usage_period_rollups_user_granularity_period_idx',
    'usage_period_rollups_user_period_start_idx',
    'usage_user_created_idx',
    'usage_monthly_chat_user_month_idx',
    'usage_monthly_app_user_month_idx',
    'usage_monthly_api_key_user_month_idx',
    'usage_daily_chat_user_date_idx',
    'usage_daily_app_user_date_idx',
    'usage_daily_api_key_user_date_idx',
    'usage_monthly_chat_user_chat_month_uq',
    'usage_monthly_app_user_app_month_uq',
    'usage_monthly_api_key_user_api_key_month_uq',
    'usage_daily_chat_user_chat_date_uq',
    'usage_daily_app_user_app_date_uq',
    'usage_daily_api_key_user_api_key_date_uq',
)
PROJECT_OWNER_CONTEXT_MIGRATION_PATH = os.getenv(
    'PROJECT_OWNER_CONTEXT_MIGRATION_PATH',
    '/usr/src/app/migrations/migrate_project_owner_context.sql',
)
PROJECT_OWNER_CONTEXT_INDEXES = (
    'project_sources_personal_source_uq',
    'project_sources_team_source_uq',
    'project_folders_team_project_idx',
    'project_items_team_project_idx',
    'project_settings_team_project_idx',
)
ENCRYPTED_SLUG_MIGRATION_PATH = os.getenv(
    'ENCRYPTED_SLUG_MIGRATION_PATH',
    '/usr/src/app/migrations/migrate_encrypted_slug_indexes.sql',
)
ENCRYPTED_SLUG_INDEXES = (
    'workflows_personal_slug_hash_uq',
    'workflows_team_slug_hash_uq',
    'projects_personal_slug_hash_uq',
    'projects_team_slug_hash_uq',
    'user_tasks_personal_slug_hash_uq',
    'user_tasks_team_slug_hash_uq',
    'user_plans_personal_slug_hash_uq',
    'user_plans_team_slug_hash_uq',
    'chats_personal_slug_hash_uq',
    'chats_team_slug_hash_uq',
)
SUB_CHAT_ORCHESTRATION_MIGRATION_PATH = os.getenv(
    'SUB_CHAT_ORCHESTRATION_MIGRATION_PATH',
    '/usr/src/app/migrations/migrate_sub_chat_orchestration_indexes.sql',
)
USER_CHAT_PREFERENCE_MIGRATION_PATH = os.getenv(
    'USER_CHAT_PREFERENCE_MIGRATION_PATH',
    '/usr/src/app/migrations/migrate_user_chat_preferences_indexes.sql',
)
AI_MEMORY_REMOVAL_MIGRATION_PATH = os.getenv(
    'AI_MEMORY_REMOVAL_MIGRATION_PATH',
    '/usr/src/app/migrations/migrate_remove_ai_memories.sql',
)
SUB_CHAT_ORCHESTRATION_INDEXES = (
    'sub_chat_orchestrations_owner_root_turn_uq',
    'sub_chat_orchestrations_owner_status_idx',
    'sub_chat_children_chat_uq',
    'sub_chat_children_orchestration_token_uq',
    'sub_chat_children_inference_task_uq',
    'sub_chat_children_orchestration_state_idx',
    'sub_chat_batches_orchestration_parent_id_uq',
    'sub_chat_batches_orchestration_claim_idx',
    'sub_chat_operations_identity_uq',
    'sub_chat_operations_orchestration_state_idx',
    'sub_chat_operations_charge_idx',
    'usage_charge_id_uq',
    'usage_user_root_created_idx',
    'usage_orchestration_created_idx',
    'billing_charge_identities_charge_uq',
    'billing_charge_identities_user_created_idx',
    'billing_refund_identities_refund_uq',
    'billing_settlement_outbox_due_idx',
    'team_credit_events_event_uq',
    'team_usage_events_event_uq',
)
EMBED_HASH_INDEXES = ('embeds_hashed_embed_id_idx',)
USER_CHAT_PREFERENCE_INDEXES = (
    'user_chat_preferences_owner_chat_uq',
    'user_chat_preferences_owner_updated_idx',
)
EMBED_HASH_BACKFILL_BATCH_SIZE = 500

BACKEND_PERMISSION_COLLECTIONS = (
    'account_export_jobs',
    'account_export_parts',
    'anonymous_free_usage_budget',
    'anonymous_free_usage_identity_daily',
    'anonymous_free_usage_reservations',
    'free_testing_credit_grants',
    'free_testing_credits_budget',
    'user_plan_key_wrappers',
    'user_task_key_wrappers',
    'user_chat_preferences',
    'user_plan_revisions',
    'user_work_dependencies',
)
BACKEND_PERMISSION_ACTIONS = ('create', 'read', 'update', 'delete')
BACKEND_PERMISSION_POLICY_NAMES = ('Backend API', 'Administrator')

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
                
        except Exception:
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


def _directus_id(value):
    if isinstance(value, dict):
        return value.get('id')
    return value


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


def primary_field_special(field_type):
    """Return Directus special metadata for a primary field type."""
    return ["uuid"] if normalize_directus_type(field_type) == "uuid" else []


def repair_primary_field_metadata(token, collection_name, field_name, field_config):
    """Align existing primary field metadata with the YAML schema.

    Older setup runs marked every primary key as a UUID, even when the YAML
    schema declared a string ID column. Directus uses that metadata when writing
    rows, so repair it whenever schemas are processed.
    """
    desired_type = normalize_directus_type(field_config.get('type', 'uuid'))
    desired_special = primary_field_special(field_config.get('type', 'uuid'))

    try:
        response = requests.get(
            f"{CMS_URL}/fields/{collection_name}/{field_name}",
            headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code != 200:
            return

        field_data = response.json().get('data', {})
        meta = field_data.get('meta') or {}
        existing_special = meta.get('special') or []
        if not isinstance(existing_special, list):
            existing_special = [existing_special] if existing_special else []

        if field_data.get('type') == desired_type and existing_special == desired_special:
            return

        patch_data = {
            "type": desired_type,
            "meta": {
                **meta,
                "special": desired_special,
            }
        }
        patch_response = requests.patch(
            f"{CMS_URL}/fields/{collection_name}/{field_name}",
            json=patch_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        if patch_response.status_code >= 400:
            print(f"Failed to repair primary field metadata for {collection_name}.{field_name}: {patch_response.status_code}")
            print(f"Response body: {patch_response.text}")
        else:
            print(f"Repaired primary field metadata for {collection_name}.{field_name}")
    except Exception as e:
        print(f"Exception while repairing primary field metadata for {collection_name}.{field_name}: {str(e)}")


def find_backend_permission_policy_id(token):
    """Find the Directus policy used by backend service writes."""
    try:
        me_response = requests.get(
            f"{CMS_URL}/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        if me_response.status_code == 200:
            role = me_response.json().get('data', {}).get('role')
            role_id = role.get('id') if isinstance(role, dict) else role
            if role_id:
                access_response = requests.get(
                    f"{CMS_URL}/access",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"filter[role][_eq]": role_id},
                )
                if access_response.status_code == 200:
                    access_rows = access_response.json().get('data', [])
                    for access_row in access_rows:
                        policy = access_row.get('policy')
                        policy_id = policy.get('id') if isinstance(policy, dict) else policy
                        if policy_id:
                            return policy_id

        response = requests.get(
            f"{CMS_URL}/policies",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            print(f"Failed to fetch Directus policies: {response.status_code}")
            print(f"Response body: {response.text}")
            return None

        policies = response.json().get('data', [])
        for policy_name in BACKEND_PERMISSION_POLICY_NAMES:
            for policy in policies:
                if policy.get('name') == policy_name and policy.get('id'):
                    return policy['id']
        print("No backend Directus policy found for collection permissions")
        return None
    except Exception as e:
        print(f"Exception while fetching Directus policies: {str(e)}")
        return None


def ensure_backend_collection_permissions(token):
    """Ensure backend-owned budget collections have explicit CRUD permissions."""
    policy_id = find_backend_permission_policy_id(token)
    if not policy_id:
        return False

    try:
        response = requests.get(
            f"{CMS_URL}/permissions",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            print(f"Failed to fetch Directus permissions: {response.status_code}")
            print(f"Response body: {response.text}")
            return False

        existing_permissions = response.json().get('data', [])
        existing = {
            (permission.get('collection'), permission.get('action'), permission.get('policy'))
            for permission in existing_permissions
        }

        success = True
        for collection_name in BACKEND_PERMISSION_COLLECTIONS:
            for action in BACKEND_PERMISSION_ACTIONS:
                permission_key = (collection_name, action, policy_id)
                if permission_key in existing:
                    continue

                payload = {
                    "collection": collection_name,
                    "action": action,
                    "policy": policy_id,
                    "permissions": {},
                    "validation": None,
                    "presets": None,
                    "fields": ["*"],
                }
                create_response = requests.post(
                    f"{CMS_URL}/permissions",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if create_response.status_code >= 400:
                    print(f"Failed to create permission for {collection_name}.{action}: {create_response.status_code}")
                    print(f"Response body: {create_response.text}")
                    success = False
                else:
                    print(f"Created permission for {collection_name}.{action}")
        return success
    except Exception as e:
        print(f"Exception while ensuring backend collection permissions: {str(e)}")
        return False

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
                print("Warning: Field type mismatch. Relation may fail.")
                
                # Try to update field type if needed
                if (local_data_type == 'uuid' and related_data_type != 'uuid') or \
                   (local_data_type != 'uuid' and related_data_type == 'uuid'):
                    print("Attempting to fix incompatible data types...")
        
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
    """
    Creates a new field or updates an existing one (only for system collections).
    For custom collections, only creates missing fields - does not update existing ones
    to preserve user changes.
    """
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
            # For existing custom collections, if field exists, we skip updating it
            # to preserve any user changes. This is expected behavior.
            # Note: This else block only executes when field exists and it's NOT a system collection
            existing_type, existing_db_type = check_field_type(token, collection_name, field_name)
            desired_db_type = map_type(field_config.get('type'), field_config.get('length'))
            force_migrate = field_config.get('force_migrate', False)
            if existing_db_type and existing_db_type.lower() != desired_db_type.lower():
                if force_migrate:
                    # force_migrate: true in YAML → apply type change via Directus PATCH
                    print(
                        f"Force-migrating {collection_name}.{field_name}: "
                        f"'{existing_db_type}' → '{desired_db_type}'"
                    )
                    patch_data = {
                        "type": field_data["type"],
                        "meta": field_data["meta"]
                    }
                    try:
                        response = requests.patch(
                            f"{CMS_URL}/fields/{collection_name}/{field_name}",
                            json=patch_data,
                            headers={"Authorization": f"Bearer {token}"}
                        )
                        if response.status_code >= 400:
                            print(f"Failed to force-migrate field: {response.status_code}")
                            print(f"Response body: {response.text}")
                        else:
                            print(f"Successfully force-migrated field {collection_name}.{field_name}")
                    except Exception as e:
                        print(f"Exception while force-migrating field {field_name}: {str(e)}")
                else:
                    print(
                        f"WARNING: {collection_name}.{field_name} type mismatch — "
                        f"schema wants '{desired_db_type}' but DB has '{existing_db_type}'. "
                        f"Add 'force_migrate: true' to the field in the YAML schema to auto-apply, "
                        f"or run: ALTER TABLE {collection_name} ALTER COLUMN {field_name} TYPE {desired_db_type};"
                    )
            else:
                print(f"Field {collection_name}.{field_name} already exists in custom collection. Skipping update to preserve user changes.")
        
        # Return True if it's a relation field, so it gets added to relations_to_create
        # Note: For existing fields in custom collections, we still check if relation exists
        # and add it if missing (handled in create_relation function)
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


def create_collection_from_config(token, collection_name, collection):
    """
    Create one collection from parsed schema config, or update missing fields/relations.
    
    Behavior:
    - For new collections: Creates the collection and all fields/relations
    - For system collections (directus_*): Updates existing fields and adds missing ones
    - For existing custom collections: Only adds missing fields (does not update existing ones
      to preserve user changes)
    
    Returns a tuple: (success: bool, newly_created: bool)
    """
    try:
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
                print(f"Custom collection {collection_name} already exists. Will check for missing fields and add them.")
                # We will process fields to add missing ones, but won't update existing fields
                # to avoid overwriting user changes.
            else:
                print(f"Creating new custom collection: {collection_name}")
                create_new = True
        
        # Create the collection if needed (non-system collections only)
        if create_new:
            # --- Collection Creation Logic ---
            primary_field = None
            # Find the primary field defined in schema
            if collection.get('fields'):
                for field_name, field_config in collection.get('fields').items():
                    if field_config.get('primary'):
                        field_type = field_config.get('type', 'uuid')
                        primary_field = {
                            "field": field_name,
                            "type": normalize_directus_type(field_type),
                            "meta": {
                                "hidden": False,
                                "readonly": False,
                                "interface": "input",
                                "special": primary_field_special(field_type),
                            },
                            "schema": {
                                "is_primary_key": True,
                                "has_auto_increment": False,
                                "data_type": map_type(field_type, field_config.get('length')),
                            }
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
        # 3. The collection already exists (to add missing fields)
        # For existing custom collections, we only add missing fields (won't update existing ones)
        should_process_fields = create_new or is_system_collection or exists

        if should_process_fields:
            # Determine processing mode for logging
            if create_new:
                mode = "newly created"
            elif is_system_collection:
                mode = "system collection (updating existing fields)"
            else:
                mode = "existing custom collection (adding missing fields only)"
            
            print(f"Processing fields and relations for {collection_name} ({mode})")
            relations_to_create = []
            
            if collection.get('fields'):
                for field_name, field_config in collection['fields'].items():
                    # Skip primary key fields (handled during collection creation or already exists)
                    if field_config.get('primary'):
                        if exists:
                            repair_primary_field_metadata(token, collection_name, field_name, field_config)
                        continue
                    
                    # Create or update the field, and check if it's a relation
                    # For existing custom collections, create_or_update_field will only create
                    # missing fields, not update existing ones (to preserve user changes)
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


def create_collection(token, schema_file):
    """
    Create collections from a schema file, or update fields/relations for existing collections.
    A single YAML file may define multiple top-level collections.

    Behavior:
    - For new collections: Creates the collection and all fields/relations
    - For system collections (directus_*): Updates existing fields and adds missing ones
    - For existing custom collections: Only adds missing fields (does not update existing ones
      to preserve user changes)

    Returns a tuple: (success: bool, newly_created: bool)
    """
    try:
        with open(schema_file, 'r') as f:
            schema = yaml.safe_load(f) or {}

        if not isinstance(schema, dict) or not schema:
            print(f"Schema file {schema_file} does not define any collections")
            return False, False

        overall_success = True
        any_newly_created = False
        for collection_name, collection in schema.items():
            success, newly_created = create_collection_from_config(token, collection_name, collection or {})
            overall_success = overall_success and success
            any_newly_created = any_newly_created or newly_created

        return overall_success, any_newly_created
    except Exception as e:
        print(f'Error processing schema file {schema_file}: {str(e)}')
        if hasattr(e, 'response') and e.response is not None:
            print(f'Response status code: {e.response.status_code}')
            print(f'Response body: {e.response.text}')
        return False, False


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
    digits = "123456789"
    
    # Generate 3 groups of 4 random digits
    part1 = ''.join(secrets.choice(digits) for _ in range(4))
    part2 = ''.join(secrets.choice(digits) for _ in range(4))
    part3 = ''.join(secrets.choice(digits) for _ in range(4))
    
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

def signup_mode_uses_invites():
    mode = os.getenv("SELF_HOST_SIGNUP_MODE", "invite_only").strip().lower()
    return mode in {"invite_only", "invite_and_domain"}


def connect_database():
    """Create the setup-only PostgreSQL connection used for index migrations."""
    import psycopg

    return psycopg.connect(
        host=os.getenv('DB_HOST', 'cms-database'),
        port=int(os.getenv('DB_PORT', '5432')),
        dbname=os.getenv('DB_DATABASE') or os.getenv('DATABASE_NAME'),
        user=os.getenv('DB_USER') or os.getenv('DATABASE_USERNAME'),
        password=os.getenv('DB_PASSWORD') or os.getenv('DATABASE_PASSWORD'),
        connect_timeout=10,
    )


def apply_and_verify_embed_hash_contract():
    """Backfill and index the embed hash used by shared-chat key lookups."""
    with connect_database() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE public.embeds "
                "ADD COLUMN IF NOT EXISTS hashed_embed_id varchar(255);"
            )

            backfilled = 0
            while True:
                cursor.execute(
                    """
                    SELECT id, embed_id
                    FROM public.embeds
                    WHERE embed_id IS NOT NULL
                      AND (hashed_embed_id IS NULL OR hashed_embed_id = '')
                    LIMIT %s
                    """,
                    (EMBED_HASH_BACKFILL_BATCH_SIZE,),
                )
                rows = cursor.fetchall()
                if not rows:
                    break

                updates = [
                    (hashlib.sha256(str(embed_id).encode()).hexdigest(), row_id)
                    for row_id, embed_id in rows
                ]
                cursor.executemany(
                    "UPDATE public.embeds SET hashed_embed_id = %s WHERE id = %s",
                    updates,
                )
                backfilled += len(updates)

            cursor.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS embeds_hashed_embed_id_idx "
                "ON public.embeds (hashed_embed_id) WHERE hashed_embed_id IS NOT NULL;"
            )
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = ANY(%s)
                """,
                (list(EMBED_HASH_INDEXES),),
            )
            installed_indexes = {row[0] for row in cursor.fetchall()}

    missing_indexes = set(EMBED_HASH_INDEXES) - installed_indexes
    if missing_indexes:
        raise RuntimeError(
            "Embed hash index verification failed: "
            + ", ".join(sorted(missing_indexes))
        )
    print(f"Verified embed hashed_embed_id contract; backfilled {backfilled} row(s)")


def apply_and_verify_chat_recovery_indexes():
    """Apply the idempotent recovery migration and require every unique index."""
    if not os.path.isfile(CHAT_RECOVERY_MIGRATION_PATH):
        raise RuntimeError(
            f"Required chat recovery migration is missing: {CHAT_RECOVERY_MIGRATION_PATH}"
        )

    with open(CHAT_RECOVERY_MIGRATION_PATH, 'r', encoding='utf-8') as migration_file:
        migration_sql = migration_file.read()

    with connect_database() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(migration_sql)
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = ANY(%s)
                """,
                (list(CHAT_RECOVERY_INDEXES),),
            )
            installed_indexes = {row[0] for row in cursor.fetchall()}

    missing_indexes = set(CHAT_RECOVERY_INDEXES) - installed_indexes
    if missing_indexes:
        raise RuntimeError(
            "Chat recovery index verification failed: "
            + ", ".join(sorted(missing_indexes))
        )
    print(f"Verified {len(CHAT_RECOVERY_INDEXES)} chat recovery indexes")


def apply_and_verify_storage_replication_indexes():
    """Apply durable regional storage identities and bounded due-work indexes."""
    if not os.path.isfile(STORAGE_REPLICATION_MIGRATION_PATH):
        raise RuntimeError(
            f"Required storage replication migration is missing: {STORAGE_REPLICATION_MIGRATION_PATH}"
        )

    with open(STORAGE_REPLICATION_MIGRATION_PATH, 'r', encoding='utf-8') as migration_file:
        migration_sql = migration_file.read()

    with connect_database() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(migration_sql)
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = ANY(%s)
                """,
                (list(STORAGE_REPLICATION_INDEXES),),
            )
            installed_indexes = {row[0] for row in cursor.fetchall()}

    missing_indexes = set(STORAGE_REPLICATION_INDEXES) - installed_indexes
    if missing_indexes:
        raise RuntimeError(
            "Storage replication index verification failed: "
            + ", ".join(sorted(missing_indexes))
        )
    print(f"Verified {len(STORAGE_REPLICATION_INDEXES)} storage replication indexes")


def apply_and_verify_workflow_runtime_indexes():
    """Apply the Workflow runtime migration before its scheduler can be enabled."""
    if not os.path.isfile(WORKFLOW_RUNTIME_MIGRATION_PATH):
        raise RuntimeError(
            f"Required workflow runtime migration is missing: {WORKFLOW_RUNTIME_MIGRATION_PATH}"
        )

    with open(WORKFLOW_RUNTIME_MIGRATION_PATH, 'r', encoding='utf-8') as migration_file:
        migration_sql = migration_file.read()

    with connect_database() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(migration_sql)
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = ANY(%s)
                """,
                (list(WORKFLOW_RUNTIME_INDEXES),),
            )
            installed_indexes = {row[0] for row in cursor.fetchall()}

    missing_indexes = set(WORKFLOW_RUNTIME_INDEXES) - installed_indexes
    if missing_indexes:
        raise RuntimeError(
            "Workflow runtime index verification failed: "
            + ", ".join(sorted(missing_indexes))
        )
    print(f"Verified {len(WORKFLOW_RUNTIME_INDEXES)} workflow runtime indexes")


def apply_and_verify_user_task_indexes():
    """Apply user task hot-path indexes before task boards and retention run."""
    if not os.path.isfile(USER_TASK_MIGRATION_PATH):
        raise RuntimeError(
            f"Required user task migration is missing: {USER_TASK_MIGRATION_PATH}"
        )

    with open(USER_TASK_MIGRATION_PATH, 'r', encoding='utf-8') as migration_file:
        migration_sql = migration_file.read()

    with connect_database() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(migration_sql)
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = ANY(%s)
                """,
                (list(USER_TASK_INDEXES),),
            )
            installed_indexes = {row[0] for row in cursor.fetchall()}

    missing_indexes = set(USER_TASK_INDEXES) - installed_indexes
    if missing_indexes:
        raise RuntimeError(
            "User task index verification failed: "
            + ", ".join(sorted(missing_indexes))
        )
    print(f"Verified {len(USER_TASK_INDEXES)} user task indexes")


def apply_and_verify_user_work_control_indexes():
    """Apply the durable unique edge index before dependency routes are enabled."""
    if not os.path.isfile(USER_WORK_CONTROL_MIGRATION_PATH):
        raise RuntimeError(f"Required work-control migration is missing: {USER_WORK_CONTROL_MIGRATION_PATH}")
    with open(USER_WORK_CONTROL_MIGRATION_PATH, 'r', encoding='utf-8') as migration_file:
        migration_sql = migration_file.read()
    with connect_database() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(migration_sql)
            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname = ANY(%s)",
                (list(USER_WORK_CONTROL_INDEXES),),
            )
            installed_indexes = {row[0] for row in cursor.fetchall()}
    missing_indexes = set(USER_WORK_CONTROL_INDEXES) - installed_indexes
    if missing_indexes:
        raise RuntimeError("Work-control index verification failed: " + ", ".join(sorted(missing_indexes)))
    print(f"Verified {len(USER_WORK_CONTROL_INDEXES)} work-control indexes")


def apply_and_verify_usage_overview_indexes():
    """Apply usage overview rollup and hot-path read indexes."""
    if not os.path.isfile(USAGE_OVERVIEW_MIGRATION_PATH):
        raise RuntimeError(
            f"Required usage overview migration is missing: {USAGE_OVERVIEW_MIGRATION_PATH}"
        )

    with open(USAGE_OVERVIEW_MIGRATION_PATH, 'r', encoding='utf-8') as migration_file:
        migration_sql = migration_file.read()

    with connect_database() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(migration_sql)
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = ANY(%s)
                """,
                (list(USAGE_OVERVIEW_INDEXES),),
            )
            installed_indexes = {row[0] for row in cursor.fetchall()}

    missing_indexes = set(USAGE_OVERVIEW_INDEXES) - installed_indexes
    if missing_indexes:
        raise RuntimeError(
            "Usage overview index verification failed: "
            + ", ".join(sorted(missing_indexes))
        )
    print(f"Verified {len(USAGE_OVERVIEW_INDEXES)} usage overview indexes")


def apply_and_verify_project_owner_context():
    """Backfill exact Project ownership and require context-aware indexes."""
    if not os.path.isfile(PROJECT_OWNER_CONTEXT_MIGRATION_PATH):
        raise RuntimeError(
            f"Required Project owner-context migration is missing: {PROJECT_OWNER_CONTEXT_MIGRATION_PATH}"
        )
    with open(PROJECT_OWNER_CONTEXT_MIGRATION_PATH, 'r', encoding='utf-8') as migration_file:
        migration_sql = migration_file.read()

    with connect_database() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(migration_sql)
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = ANY(%s)
                """,
                (list(PROJECT_OWNER_CONTEXT_INDEXES),),
            )
            installed_indexes = {row[0] for row in cursor.fetchall()}

    missing_indexes = set(PROJECT_OWNER_CONTEXT_INDEXES) - installed_indexes
    if missing_indexes:
        raise RuntimeError(
            "Project owner-context index verification failed: "
            + ", ".join(sorted(missing_indexes))
        )
    print(f"Verified {len(PROJECT_OWNER_CONTEXT_INDEXES)} Project owner-context indexes")


def apply_and_verify_encrypted_slug_indexes():
    """Apply and require owner/team scoped encrypted slug duplicate guards."""
    if not os.path.isfile(ENCRYPTED_SLUG_MIGRATION_PATH):
        raise RuntimeError(
            f"Required encrypted slug migration is missing: {ENCRYPTED_SLUG_MIGRATION_PATH}"
        )
    with open(ENCRYPTED_SLUG_MIGRATION_PATH, 'r', encoding='utf-8') as migration_file:
        migration_sql = migration_file.read()

    with connect_database() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(migration_sql)
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = ANY(%s)
                """,
                (list(ENCRYPTED_SLUG_INDEXES),),
            )
            installed_indexes = {row[0] for row in cursor.fetchall()}

    missing_indexes = set(ENCRYPTED_SLUG_INDEXES) - installed_indexes
    if missing_indexes:
        raise RuntimeError(
            "Encrypted slug index verification failed: "
            + ", ".join(sorted(missing_indexes))
        )
    print(f"Verified {len(ENCRYPTED_SLUG_INDEXES)} encrypted slug indexes")


def apply_and_verify_sub_chat_orchestration_indexes():
    """Apply and require durable sub-chat orchestration identity indexes."""
    if not os.path.isfile(SUB_CHAT_ORCHESTRATION_MIGRATION_PATH):
        raise RuntimeError(
            "Required sub-chat orchestration migration is missing: "
            f"{SUB_CHAT_ORCHESTRATION_MIGRATION_PATH}"
        )
    with open(SUB_CHAT_ORCHESTRATION_MIGRATION_PATH, 'r', encoding='utf-8') as migration_file:
        migration_sql = migration_file.read()

    with connect_database() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(migration_sql)
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = ANY(%s)
                """,
                (list(SUB_CHAT_ORCHESTRATION_INDEXES),),
            )
            installed_indexes = {row[0] for row in cursor.fetchall()}

    missing_indexes = set(SUB_CHAT_ORCHESTRATION_INDEXES) - installed_indexes
    if missing_indexes:
        raise RuntimeError(
            "Sub-chat orchestration index verification failed: "
            + ", ".join(sorted(missing_indexes))
        )
    print(f"Verified {len(SUB_CHAT_ORCHESTRATION_INDEXES)} sub-chat orchestration indexes")


def apply_and_verify_user_chat_preference_indexes():
    """Apply unique owner/chat indexes for encrypted AI model preferences."""
    if not os.path.isfile(USER_CHAT_PREFERENCE_MIGRATION_PATH):
        raise RuntimeError(
            f"Required user chat preference migration is missing: {USER_CHAT_PREFERENCE_MIGRATION_PATH}"
        )

    with open(USER_CHAT_PREFERENCE_MIGRATION_PATH, 'r', encoding='utf-8') as migration_file:
        migration_sql = migration_file.read()

    with connect_database() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(migration_sql)
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = ANY(%s)
                """,
                (list(USER_CHAT_PREFERENCE_INDEXES),),
            )
            installed_indexes = {row[0] for row in cursor.fetchall()}

    missing_indexes = set(USER_CHAT_PREFERENCE_INDEXES) - installed_indexes
    if missing_indexes:
        raise RuntimeError(
            "User chat preference index verification failed: "
            + ", ".join(sorted(missing_indexes))
        )
    print(f"Verified {len(USER_CHAT_PREFERENCE_INDEXES)} user chat preference indexes")


def apply_and_verify_ai_memory_removal():
    """Delete only obsolete AI-owned memory rows and verify none remain."""
    if not os.path.isfile(AI_MEMORY_REMOVAL_MIGRATION_PATH):
        raise RuntimeError(
            "Required AI-memory removal migration is missing: "
            f"{AI_MEMORY_REMOVAL_MIGRATION_PATH}"
        )

    with open(AI_MEMORY_REMOVAL_MIGRATION_PATH, 'r', encoding='utf-8') as migration_file:
        migration_sql = migration_file.read()

    with connect_database() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(migration_sql)
            deleted_count = cursor.rowcount
            cursor.execute(
                "SELECT COUNT(*) FROM public.user_app_settings_and_memories WHERE app_id = %s",
                ('ai',),
            )
            remaining_count = cursor.fetchone()[0]

    if remaining_count:
        raise RuntimeError(
            f"AI-memory removal verification failed: {remaining_count} row(s) remain"
        )
    print(f"Verified AI-memory removal; deleted {deleted_count} active row(s)")
    return deleted_count


def verify_chat_recovery_endpoint():
    """Require the baked extension to answer an authenticated metadata-only read."""
    if not INTERNAL_API_SHARED_TOKEN:
        raise RuntimeError('INTERNAL_API_SHARED_TOKEN is required for Directus setup')
    response = requests.post(
        f"{CMS_URL}/chat-recovery-transaction/",
        headers={"X-Internal-Service-Token": INTERNAL_API_SHARED_TOKEN},
        json={
            "operation": "list_available_jobs",
            "data": {
                "protocol_version": 1,
                "hashed_user_id": "0" * 64,
                "device_hash": "setup-health-check",
            },
        },
        timeout=10,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Chat recovery endpoint verification failed with HTTP {response.status_code}"
        )
    jobs = response.json().get('data', {}).get('jobs')
    if not isinstance(jobs, list):
        raise RuntimeError('Chat recovery endpoint returned an invalid health response')
    print('Verified chat recovery Directus endpoint')


def verify_sub_chat_orchestration_endpoint():
    """Require the internal orchestration endpoint to pass its metadata-only health check."""
    if not INTERNAL_API_SHARED_TOKEN:
        raise RuntimeError('INTERNAL_API_SHARED_TOKEN is required for Directus setup')
    response = requests.post(
        f"{CMS_URL}/sub-chat-orchestration-transaction/",
        headers={"X-Internal-Service-Token": INTERNAL_API_SHARED_TOKEN},
        json={"operation": "health_check", "data": {"protocol_version": 1}},
        timeout=10,
    )
    if response.status_code != 200:
        raise RuntimeError(
            "Sub-chat orchestration endpoint health check failed: "
            f"HTTP {response.status_code}"
        )
    data = response.json().get('data', {})
    if data.get('status') != 'ok' or data.get('protocol_version') != 1:
        raise RuntimeError('Sub-chat orchestration endpoint returned an invalid health response')
    print('Verified sub-chat orchestration Directus endpoint')


def verify_anonymous_usage_endpoint():
    """Require the atomic anonymous usage endpoint to pass its internal health check."""
    if not INTERNAL_API_SHARED_TOKEN:
        raise RuntimeError('INTERNAL_API_SHARED_TOKEN is required for Directus setup')
    response = requests.post(
        f"{CMS_URL}/anonymous-usage-transaction/",
        headers={"X-Internal-Service-Token": INTERNAL_API_SHARED_TOKEN},
        json={"operation": "health_check", "data": {"protocol_version": 1}},
        timeout=10,
    )
    if response.status_code != 200:
        raise RuntimeError(
            "Anonymous usage endpoint health check failed: "
            f"HTTP {response.status_code}"
        )
    data = response.json().get('data', {})
    if data.get('status') != 'ok' or data.get('protocol_version') != 1:
        raise RuntimeError('Anonymous usage endpoint returned an invalid health response')
    print('Verified anonymous usage Directus endpoint')

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

                print("\n--- Ensuring backend collection permissions ---")
                ensure_backend_collection_permissions(token)

        print("\n--- Ensuring embed hash lookup contract ---")
        apply_and_verify_embed_hash_contract()

        print("\n--- Applying chat recovery database indexes ---")
        apply_and_verify_chat_recovery_indexes()

        print("\n--- Applying storage replication database indexes ---")
        apply_and_verify_storage_replication_indexes()

        print("\n--- Verifying chat recovery Directus endpoint ---")
        verify_chat_recovery_endpoint()

        print("\n--- Applying workflow runtime database indexes ---")
        apply_and_verify_workflow_runtime_indexes()

        print("\n--- Applying user task database indexes ---")
        apply_and_verify_user_task_indexes()

        print("\n--- Applying user work-control database indexes ---")
        apply_and_verify_user_work_control_indexes()

        print("\n--- Applying usage overview database indexes ---")
        apply_and_verify_usage_overview_indexes()

        print("\n--- Applying Project owner-context migration ---")
        apply_and_verify_project_owner_context()

        print("\n--- Applying encrypted slug duplicate indexes ---")
        apply_and_verify_encrypted_slug_indexes()

        print("\n--- Applying sub-chat orchestration database indexes ---")
        apply_and_verify_sub_chat_orchestration_indexes()

        print("\n--- Applying user chat preference database indexes ---")
        apply_and_verify_user_chat_preference_indexes()

        print("\n--- Removing obsolete AI-owned memories ---")
        apply_and_verify_ai_memory_removal()

        print("\n--- Verifying sub-chat orchestration Directus endpoint ---")
        verify_sub_chat_orchestration_endpoint()

        print("\n--- Verifying anonymous usage Directus endpoint ---")
        verify_anonymous_usage_endpoint()

        # Only create the first signup invite code if the 'invite_codes'
        # collection was newly created during this run (i.e., first setup).
        if invite_codes_newly_created:
            if not signup_mode_uses_invites():
                print("\nFirst startup detected, but signup mode does not require invite codes. Skipping first invite code creation.")
                print('\nSchema setup complete')
                return

            print("\nFirst startup detected (invite_codes collection created) - creating first signup invite code...")
            invite_code = os.getenv("SELF_HOST_FIRST_INVITE_CODE") or generate_invite_code()
            
            # Store as a normal signup invite. Admin access is granted separately
            # with `openmates server make-admin <email>` after signup.
            if store_invite_code(token, invite_code, is_admin=False):
                print("\n==================================")
                print("IMPORTANT: Use this invite code to create the first user:")
                print(f"First Signup Invite Code: {invite_code}")
                print("After signup, run: openmates server make-admin <email>")
                print("==================================\n")
            else:
                print("Failed to store first signup invite code")
        
        print('\nSchema setup complete')
        
    except Exception as e:
        print(f'Schema setup failed: {str(e)}')
        # Optionally re-raise or exit differently
        import traceback
        traceback.print_exc()
        exit(1)

if __name__ == "__main__":
    setup_schemas()
