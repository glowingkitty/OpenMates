import requests
import os
import logging
from dotenv import load_dotenv
import secrets
import string
import time
import sys

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Update the Strapi admin user creation endpoint
cms_url = f"http://cms:{os.getenv('CMS_PORT')}"
admin_register_url = f"{cms_url}/admin/register-admin"
create_api_token_url = f"{cms_url}/admin/api-tokens"

# Function to generate a random email
def generate_random_email():
    """
    Generate a random lowercase email of the specified length.
    """
    # Generate a random string of 8 lowercase characters for the email prefix
    email_prefix = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    # Use a fixed domain for the email
    return f"{email_prefix}@example.com"

# Function to generate a random password
def generate_random_password(length=20):
    """
    Generate a random password of the specified length that meets Strapi CMS requirements.

    The password will always contain at least one lowercase letter, one uppercase letter,
    one digit, and one special character.
    """
    # Define character sets
    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits
    special = string.punctuation

    # Ensure at least one character from each set
    password = [
        secrets.choice(lowercase),
        secrets.choice(uppercase),
        secrets.choice(digits),
        secrets.choice(special)
    ]

    # Fill the rest of the password length with random characters
    remaining_length = length - len(password)
    all_characters = lowercase + uppercase + digits + special
    password.extend(secrets.choice(all_characters) for _ in range(remaining_length))

    # Shuffle the password to randomize character positions
    secrets.SystemRandom().shuffle(password)

    return ''.join(password)

def is_cms_online():
    """
    Check if the Strapi CMS is online and accessible.
    """
    try:
        response = requests.get(f"{cms_url}/_health")
        return response.status_code == 204
    except requests.RequestException:
        return False

def create_super_admin():
    """
    Create a super admin account in the Strapi CMS.
    """
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    admin_data = {
        "email": admin_email if admin_email and admin_email != "" else generate_random_email(),
        "password": admin_password if admin_password and admin_password != "" else generate_random_password(),
        "firstname": "Super",
        "lastname": "Admin",
    }

    try:
        response = requests.post(admin_register_url, json=admin_data)
        if response.status_code == 200 or response.status_code == 201:
            logger.info("Super admin created successfully.")
            return admin_email, admin_password
        else:
            logger.error(f"Failed to create super admin. Status code: {response.status_code}")
            logger.error(f"Error message: {response.text}")
            return None, None
    except Exception as e:
        logger.error(f"Error in create_super_admin: {e}")
        return None, None

def login_admin(email, password):
    """
    Log in as admin and return the JWT token.
    """
    login_url = f"{cms_url}/admin/login"
    login_data = {
        "email": email,
        "password": password
    }
    try:
        response = requests.post(login_url, json=login_data)
        if response.status_code == 200:
            return response.json().get('data', {}).get('token')
        else:
            logger.error(f"Admin login failed. Status code: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error during admin login: {e}")
        return None

def create_api_token(admin_token):
    """
    Create an API token for the Strapi user.
    """
    headers = {
        "Authorization": f"Bearer {admin_token}",
        "Content-Type": "application/json"
    }
    token_data = {
        "name": "API User Token",
        "description": "Token for API access",
        "type": "full-access"
    }

    try:
        response = requests.post(create_api_token_url, json=token_data, headers=headers)
        if response.status_code == 201:
            logger.info("API token created successfully.")
            return response.json()["data"]["accessKey"]
        else:
            logger.error(f"Failed to create API token. Status code: {response.status_code}")
            logger.error(f"Error message: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Error creating API token: {e}")
        return None

def main():
    """
    Main function to set up Strapi CMS with super admin and API token.
    """
    logger.info("Waiting for Strapi CMS to come online...")

    attempts = 0
    max_attempts = 30

    while not is_cms_online():
        attempts += 1
        if attempts > max_attempts:
            logger.error(f"CMS not online after {max_attempts} attempts. Exiting with error.")
            sys.exit(1)
        logger.debug(f"CMS not yet online. Attempt {attempts}/{max_attempts}. Retrying in 5 seconds...")
        time.sleep(5)

    logger.info("Strapi CMS is online and accessible.")

    # Create super admin
    admin_email, admin_password = create_super_admin()
    if not admin_email or not admin_password:
        logger.error("Failed to create super admin. Exiting.")
        sys.exit(1)

    # Login as super admin
    admin_token = login_admin(admin_email, admin_password)
    if not admin_token:
        logger.error("Failed to login as super admin. Exiting.")
        sys.exit(1)

    # Create API token
    api_token = create_api_token(admin_token)
    if not api_token:
        logger.error("Failed to create API token. Exiting.")
        sys.exit(1)

    # Log credentials and token
    logger.info("="*50)
    logger.info("IMPORTANT: Save the following credentials and token")
    logger.info("="*50)
    logger.info(f"ADMIN_EMAIL={admin_email}")
    logger.info(f"ADMIN_PASSWORD={admin_password}")
    logger.info(f"CMS_TOKEN={api_token}")
    logger.info("="*50)

if __name__ == "__main__":
    main()