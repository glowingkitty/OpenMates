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

# Events we want Revolut to notify us about
# Start with the most critical one, can add more later via API update or manually
WEBHOOK_EVENTS = [
    "ORDER_COMPLETED",
    # "ORDER_FAILED", # Temporarily removed for testing registration
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

# --- Main Script Logic ---
def main():
    parser = argparse.ArgumentParser(
        description="Register a webhook endpoint with Revolut Merchant API and retrieve the signing secret."
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
    parser.add_argument(
        "--webhook-url",
        required=True,
        help="The full HTTPS URL of your API's webhook endpoint (e.g., https://api.yourdomain.com/v1/payments/webhook)."
    )

    args = parser.parse_args()

    # Validate webhook URL format (basic check)
    if not args.webhook_url.startswith("https://"):
        print_error("Webhook URL must start with https://")
        sys.exit(1)

    # Determine Revolut API base URL
    base_url = REVOLUT_API_URLS.get(args.environment)
    if not base_url:
        # This should not happen due to argparse choices, but check anyway
        print_error(f"Invalid environment specified: {args.environment}")
        sys.exit(1)

    webhook_api_url = f"{base_url}/webhooks"

    # Prepare request payload and headers
    payload = json.dumps({
        "url": args.webhook_url,
        "events": WEBHOOK_EVENTS
    })
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {args.api_key}'
    }

    print(f"Attempting to register webhook for environment: {args.environment}")
    print(f"Target URL: {args.webhook_url}")
    print(f"Events: {', '.join(WEBHOOK_EVENTS)}")
    print(f"Revolut API Endpoint: {webhook_api_url}")

    try:
        response = requests.post(webhook_api_url, headers=headers, data=payload, timeout=30)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        # Process successful response
        response_data = response.json()
        webhook_id = response_data.get("id")
        signing_secret = response_data.get("signing_secret")

        if not webhook_id or not signing_secret:
            print_error("Webhook registered, but response did not contain expected 'id' or 'signing_secret'.")
            print(f"Response Body:\n{json.dumps(response_data, indent=2)}")
            sys.exit(1)

        print_success("Webhook registered successfully!")
        print(f"  Webhook ID: {webhook_id}")
        print(f"  Signing Secret: {signing_secret}")

        # Provide instructions for Vault
        vault_key_name = VAULT_SECRET_NAMES.get(args.environment)
        print_instruction(f"IMPORTANT: Copy the 'Signing Secret' above and store it securely in Vault.")
        print_instruction(f"The Vault key name should be: {vault_key_name}")

    except requests.exceptions.HTTPError as http_err:
        print_error(f"HTTP error occurred: {http_err}")
        try:
            error_details = http_err.response.json()
            print(f"Error Details: {json.dumps(error_details, indent=2)}")
        except json.JSONDecodeError:
            print(f"Raw Error Response: {http_err.response.text}")
        sys.exit(1)
    except requests.exceptions.RequestException as req_err:
        print_error(f"Request error occurred: {req_err}")
        sys.exit(1)
    except Exception as e:
        print_error(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Create scripts directory if it doesn't exist
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(scripts_dir):
         try:
             os.makedirs(scripts_dir)
             print(f"Created directory: {scripts_dir}")
         except OSError as e:
             print_error(f"Failed to create directory {scripts_dir}: {e}")
             # Continue anyway, maybe permissions issue later

    main()