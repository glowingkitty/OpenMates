import requests
import os
import logging
from dotenv import load_dotenv, set_key
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

def set_key_preserve_format(filename, key, value):
    """
    Update or add a key-value pair in the .env file while preserving its format.

    Args:
    filename (str): Path to the .env file
    key (str): The key to set or update
    value (str): The value to set
    """
    # Read the current contents of the file
    with open(filename, 'r') as file:
        lines = file.readlines()

    # Flag to check if the key was found and updated
    key_updated = False

    # Update the file contents
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            key_updated = True
            break

    # If the key wasn't found, add it to the end of the file
    if not key_updated:
        lines.append(f"{key}={value}\n")

    # Write the updated contents back to the file
    with open(filename, 'w') as file:
        file.writelines(lines)

    logger.debug(f"Updated {key} in {filename}")

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
    Attempt to create an admin user in the Strapi CMS and verify the account.
    """
    try:
        # Load the current .env file
        dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
        load_dotenv(dotenv_path)

        # Admin user details
        admin_email = os.getenv("ADMIN_EMAIL")
        admin_password = os.getenv("ADMIN_PASSWORD")
        admin_data = {
            "email": admin_email if admin_email and admin_email != "" else generate_random_email(),
            "password": admin_password if admin_password and admin_password != "" else generate_random_password(),
            "firstname": "Admin",
            "lastname": "User",
        }

        logger.debug("Attempting to create admin user")
        logger.debug(f"Admin register URL: {admin_register_url}")

        response = requests.post(admin_register_url, json=admin_data)

        if response.status_code == 200:
            logger.info("Admin user created successfully.")

            # Verify the admin account by attempting to log in
            if verify_admin_login(admin_data["email"], admin_data["password"]):
                logger.info("Admin account verified successfully.")
            else:
                logger.error("Admin account creation successful, but login verification failed.")

            # Output the admin credentials using logger
            logger.info(" ")
            logger.info("="*50)
            logger.info("IMPORTANT: Update the following credentials to your .env file")
            logger.info("="*50)
            logger.info(f"ADMIN_EMAIL={admin_data['email']}")
            logger.info(f"ADMIN_PASSWORD={admin_data['password']}")
            logger.info(f"CMS_TOKEN={response.json()['data']['token']}")
            logger.info("="*50)
            logger.info("After updating the .env file, execute:")
            logger.info("docker-compose -f server/docker-compose.yml down && docker-compose -f server/docker-compose.yml up --build -d")
            logger.info("="*50)
            logger.info(" ")

        elif response.status_code == 400 and "You cannot register a new super admin" in response.text:
            logger.info("Admin already setup. Attempting to verify existing account.")
            if verify_admin_login(admin_email, admin_password):
                logger.info("Existing admin account verified successfully.")
            else:
                logger.error("Existing admin account verification failed.")
        else:
            logger.error(f"Failed to create admin user. Status code: {response.status_code}")
            logger.error(f"Error message: {response.text}")
    except Exception as e:
        logger.error(f"Error in create_admin_user: {e}")
        logger.exception("Full traceback:")

def verify_admin_login(email, password):
    """
    Verify admin login by attempting to authenticate with the Strapi API.
    """
    login_url = f"{cms_url}/admin/login"
    login_data = {
        "email": email,
        "password": password
    }
    try:
        response = requests.post(login_url, json=login_data)
        if response.status_code == 200:
            logger.info("Admin login successful.")
            return True
        else:
            logger.error(f"Admin login failed. Status code: {response.status_code}")
            logger.error(f"Error message: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error during admin login verification: {e}")
        return False

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