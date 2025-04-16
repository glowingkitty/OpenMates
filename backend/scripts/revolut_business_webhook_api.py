import requests
import json
import argparse
import sys
import os

# --- Configuration ---
REVOLUT_API_URLS = {
    "sandbox": "https://sandbox-merchant.revolut.com/api/1.0",
    "production": "https://merchant.revolut.com/api/1.0"
}

# Events we want Revolut to notify us about for registration/update
DEFAULT_WEBHOOK_EVENTS = [
    "ORDER_COMPLETED",
    "ORDER_CANCELLED",
]

VAULT_SECRET_NAMES = {
    "sandbox": "API_SECRET__REVOLUT_BUSINESS_MERCHANT_SANDBOX_WEBHOOK_SECRET",
    "production": "API_SECRET__REVOLUT_BUSINESS_MERCHANT_PRODUCTION_WEBHOOK_SECRET"
}

# --- Helper Functions ---
def print_error(message):
    """Prints an error message to stderr."""
    print(f"ERROR: {message}", file=sys.stderr)

def print_success(message):
    """Prints a success message."""
    print(f"SUCCESS: {message}")

def print_instruction(message):
    """Prints an instructional message."""
    print(f"\n>>> {message}")

def get_base_url(environment):
    """Gets the base API URL for the given environment."""
    base_url = REVOLUT_API_URLS.get(environment)
    if not base_url:
        print_error(f"Invalid environment specified: {environment}")
        sys.exit(1)
    return base_url

def make_api_request(method, url, api_key, data=None):
    """Makes a request to the Revolut API."""
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }
    try:
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, timeout=30)
        elif method.upper() == 'POST':
            json_payload = json.dumps(data) if data else None
            print(f"DEBUG: Sending POST request to {url} with payload: {json_payload}") # Added payload logging
            response = requests.post(url, headers=headers, data=json_payload, timeout=30)
        elif method.upper() == 'PUT':
            json_payload = json.dumps(data) if data else None
            print(f"DEBUG: Sending PUT request to {url} with payload: {json_payload}") # Added payload logging
            response = requests.put(url, headers=headers, data=json_payload, timeout=30)
        elif method.upper() == 'DELETE': # Added DELETE method support
            response = requests.delete(url, headers=headers, timeout=30)
        else:
            print_error(f"Unsupported HTTP method: {method}")
            return None

        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        if response.status_code == 204:
             return {} # Return empty dict for No Content (common for DELETE/PUT success)
        return response.json()

    except requests.exceptions.HTTPError as http_err:
        print_error(f"HTTP error occurred: {http_err}")
        try:
            error_details = http_err.response.json()
            print(f"Error Details: {json.dumps(error_details, indent=2)}")
        except json.JSONDecodeError:
            print(f"Raw Error Response: {http_err.response.text}")
        # Specific handling for 404 on GET/PUT/DELETE
        if http_err.response.status_code == 404 and method.upper() in ['GET', 'PUT', 'DELETE']:
             print_error(f"Webhook with the specified ID not found.")
        return None
    except requests.exceptions.RequestException as req_err:
        print_error(f"Request error occurred: {req_err}")
        return None
    except Exception as e:
        print_error(f"An unexpected error occurred: {e}")
        return None

# --- Command Functions ---

def list_webhooks(args):
    """Lists registered webhooks."""
    base_url = get_base_url(args.environment)
    webhook_api_url = f"{base_url}/webhooks"

    print(f"Attempting to list webhooks for environment: {args.environment}")
    print(f"Revolut API Endpoint: {webhook_api_url}")

    response_data = make_api_request('GET', webhook_api_url, args.api_key)

    if response_data is not None:
        print_success("Successfully retrieved webhook list:")
        print(json.dumps(response_data, indent=2))
    else:
        print_error("Failed to retrieve webhook list.")
        sys.exit(1)

def get_webhook(args):
    """Retrieves details for a specific webhook."""
    base_url = get_base_url(args.environment)
    webhook_api_url = f"{base_url}/webhooks/{args.webhook_id}"

    print(f"Attempting to retrieve webhook ID: {args.webhook_id} for environment: {args.environment}")
    print(f"Revolut API Endpoint: {webhook_api_url}")

    response_data = make_api_request('GET', webhook_api_url, args.api_key)

    if response_data is not None:
        print_success(f"Successfully retrieved details for webhook ID: {args.webhook_id}")
        print(json.dumps(response_data, indent=2))
    else:
        print_error(f"Failed to retrieve details for webhook ID: {args.webhook_id}.")
        sys.exit(1)


def register_webhook(args):
    """Registers a new webhook."""
    if not args.webhook_url.startswith("https://"):
        print_error("Webhook URL must start with https://")
        sys.exit(1)

    base_url = get_base_url(args.environment)
    webhook_api_url = f"{base_url}/webhooks"

    payload = {
        "url": args.webhook_url,
        "events": args.events or DEFAULT_WEBHOOK_EVENTS
    }

    print(f"Attempting to register webhook for environment: {args.environment}")
    print(f"Target URL: {args.webhook_url}")
    print(f"Events: {', '.join(payload['events'])}")
    print(f"Revolut API Endpoint: {webhook_api_url}")

    response_data = make_api_request('POST', webhook_api_url, args.api_key, data=payload)

    if response_data:
        webhook_id = response_data.get("id")
        signing_secret = response_data.get("signing_secret")

        if not webhook_id or not signing_secret:
            print_error("Webhook registered, but response did not contain expected 'id' or 'signing_secret'.")
            print(f"Response Body:\n{json.dumps(response_data, indent=2)}")
            sys.exit(1)

        print_success("Webhook registered successfully!")
        print(f"  Webhook ID: {webhook_id}")
        print(f"  Signing Secret: {signing_secret}")

        vault_key_name = VAULT_SECRET_NAMES.get(args.environment)
        print_instruction(f"IMPORTANT: Copy the 'Signing Secret' above and store it securely in Vault.")
        print_instruction(f"The Vault key name should be: {vault_key_name}")
        print_instruction("If updating an existing webhook, the signing secret might remain the same, but verify.")
    else:
        print_error("Failed to register webhook.")
        sys.exit(1)

def update_webhook(args):
    """Updates an existing webhook."""
    if not args.webhook_url.startswith("https://"):
        print_error("Webhook URL must start with https://")
        sys.exit(1)

    base_url = get_base_url(args.environment)
    webhook_api_url = f"{base_url}/webhooks/{args.webhook_id}"

    payload = {
        "url": args.webhook_url,
        "events": args.events # Use provided events (required for update)
    }

    print(f"Attempting to update webhook ID: {args.webhook_id} for environment: {args.environment}")
    print(f"New Target URL: {args.webhook_url}")
    print(f"New Events: {', '.join(payload['events'])}")
    print(f"Revolut API Endpoint: {webhook_api_url}")

    response_data = make_api_request('PUT', webhook_api_url, args.api_key, data=payload)

    if response_data is not None:
        if response_data:
             updated_id = response_data.get("id")
             print_success(f"Webhook {updated_id} updated successfully!")
             print(f"  New URL: {response_data.get('url')}")
             print(f"  New Events: {', '.join(response_data.get('events', []))}")
        else:
             print_success(f"Webhook {args.webhook_id} update request sent successfully (check details via 'list' or 'get' command).")
    else:
        print_error(f"Failed to update webhook {args.webhook_id}.")
        sys.exit(1)

def delete_webhook(args):
    """Deletes a specific webhook."""
    base_url = get_base_url(args.environment)
    webhook_api_url = f"{base_url}/webhooks/{args.webhook_id}" # Append webhook ID

    print(f"Attempting to delete webhook ID: {args.webhook_id} for environment: {args.environment}")
    print(f"Revolut API Endpoint: {webhook_api_url}")

    response_data = make_api_request('DELETE', webhook_api_url, args.api_key)

    # DELETE usually returns 204 No Content on success
    if response_data is not None: # Check if request itself succeeded
         print_success(f"Webhook {args.webhook_id} deleted successfully.")
    else:
        print_error(f"Failed to delete webhook ID: {args.webhook_id}.")
        sys.exit(1)


# --- Main Script Logic ---
def main():
    parser = argparse.ArgumentParser(
        description="Manage Revolut Merchant API webhooks (register, list, update, get, delete)." # Added delete
    )
    parser.add_argument(
        "--environment",
        required=True,
        choices=["sandbox", "production"],
        help="The Revolut environment to target."
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="The Revolut Secret API Key for the specified environment."
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Action to perform")

    # Subparser for the 'register' command
    parser_register = subparsers.add_parser("register", help="Register a new webhook.")
    parser_register.add_argument(
        "--webhook-url",
        required=True,
        help="The full HTTPS URL of your API's webhook endpoint."
    )
    parser_register.add_argument(
        "--events",
        nargs='+',
        help=f"Specific events to subscribe to (default: {', '.join(DEFAULT_WEBHOOK_EVENTS)})."
    )
    parser_register.set_defaults(func=register_webhook)

    # Subparser for the 'list' command
    parser_list = subparsers.add_parser("list", help="List currently registered webhooks.")
    parser_list.set_defaults(func=list_webhooks)

    # Subparser for the 'get' command
    parser_get = subparsers.add_parser("get", help="Get details for a specific webhook.")
    parser_get.add_argument(
        "--webhook-id",
        required=True,
        help="The ID of the webhook to retrieve."
    )
    parser_get.set_defaults(func=get_webhook)

    # Subparser for the 'update' command
    parser_update = subparsers.add_parser("update", help="Update an existing webhook.")
    parser_update.add_argument(
        "--webhook-id",
        required=True,
        help="The ID of the webhook to update."
    )
    parser_update.add_argument(
        "--webhook-url",
        required=True,
        help="The new (or current) full HTTPS URL for the webhook."
    )
    parser_update.add_argument(
        "--events",
        nargs='+',
        required=True,
        help="The complete list of events the webhook should subscribe to after update."
    )
    parser_update.set_defaults(func=update_webhook)

    # Subparser for the 'delete' command
    parser_delete = subparsers.add_parser("delete", help="Delete a specific webhook.")
    parser_delete.add_argument(
        "--webhook-id",
        required=True,
        help="The ID of the webhook to delete."
    )
    parser_delete.set_defaults(func=delete_webhook)


    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(scripts_dir):
         try:
             os.makedirs(scripts_dir)
             print(f"Created directory: {scripts_dir}")
         except OSError as e:
             print_error(f"Failed to create directory {scripts_dir}: {e}")

    main()