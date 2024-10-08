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

def create_admin_user():
    """
    Attempt to create an admin user in the Strapi CMS.
    If an admin already exists, log the information and exit successfully.
    """
    try:
        # Admin user details with random email and password
        admin_email_loaded = os.getenv("ADMIN_EMAIL")
        admin_password_loaded = os.getenv("ADMIN_PASSWORD")
        admin_data = {
            "email": admin_email_loaded if admin_email_loaded and admin_email_loaded != "" else generate_random_email(),
            "password": admin_password_loaded if admin_password_loaded and admin_password_loaded != "" else generate_random_password(),
            "firstname": "Admin",
            "lastname": "User",
        }

        logger.debug(f"Admin data: {admin_data}")

        response = requests.post(admin_register_url, json=admin_data)

        if response.status_code == 200:
            logger.info("Admin user created successfully.")
        elif response.status_code == 400 and "You cannot register a new super admin" in response.text:
            logger.info("Admin already setup. All good.")
            sys.exit(0)  # Exit with code 0 - all good
        else:
            logger.error(f"Failed to create admin user. Status code: {response.status_code}")
            logger.error(f"Error message: {response.text}")
    except Exception as e:
        logger.error(f"Error creating admin user: {e}")

def main():
    """
    Main function to check CMS availability and create admin user if necessary.
    """
    logger.info("Waiting for Strapi CMS to come online...")

    # Initialize attempt counter
    attempts = 0
    max_attempts = 30

    # Wait for the CMS to be online
    while not is_cms_online():
        attempts += 1
        if attempts > max_attempts:
            logger.error(f"CMS not online after {max_attempts} attempts. Exiting with error.")
            sys.exit(1)

        logger.debug(f"CMS not yet online. Attempt {attempts}/{max_attempts}. Retrying in 5 seconds...")
        time.sleep(5)

    logger.info("Strapi CMS is online and accessible.")

    # Directly attempt to create an admin user
    logger.info("Attempting to create admin user...")
    create_admin_user()

if __name__ == "__main__":
    main()