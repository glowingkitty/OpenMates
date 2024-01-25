################

# Default Imports

################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.finance.banks.revolut_business.authentification.generate_private_and_public_certificate import generate_private_and_public_certificate
import json
from datetime import datetime, timedelta
import base64
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key


def base64_url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=')


def sign_with_private_key(data, private_key_path):
    with open(private_key_path, 'rb') as key_file:
        private_key = load_pem_private_key(key_file.read(), password=None, backend=default_backend())
    
    signature = private_key.sign(
        data,
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    
    return base64_url_encode(signature)


def get_authcode_and_jwt() -> dict:
    try:
        add_to_log(module_name="Revolut Business", color="blue", state="start")
        add_to_log("Getting the authorization code and JWT ...")

        secrets = load_secrets()
        
        add_to_log("Checking if the private and public certificates exist ...")
        generate_private_and_public_certificate()
        
        add_to_log("Log in to the Revolut Business app (https://business.revolut.com/settings/api), and go to Settings > Business API.")
        add_to_log("-> Click 'Add API certificate' in Revolut Business. Then press 'Enter' here to continue ...")
        input()
        # load the public certificate
        target_folder = re.sub('OpenMates.*', 'OpenMates/my_profile/secrets/revolut_business', full_current_path)
        with open(f"{target_folder}/publiccert.cer", 'r') as f:
            public_cert = f.read()
        add_to_log("Let's set up the certificate in Revolut Business.")
        add_to_log("Certificate title: give it a name, e.g., 'OpenMates'")
        add_to_log("-> Press 'Enter' once you entered the certificate title")
        input()
        add_to_log("OAuth redirect URI: enter a redirect URI, e.g., 'https://glowingkitty.com'")
        add_to_log("-> What is the redirect URI you entered? Enter it here and press 'Enter' to continue ...")
        redirect_uri = input()
        # make sure that the redirect URI is entered correctly
        while len(redirect_uri) < 5:
            add_to_log("The redirect URI is too short. Please enter the redirect URI correctly and press 'Enter' to continue ...")
            redirect_uri = input()
        # get the part behind ://, e.g., glowingkitty.com
        redirect_uri = re.sub('.*://', '', redirect_uri)
        add_to_log("X509 public key: Copy and paste the following content:")
        print(public_cert)
        add_to_log("-> Paste the X509 public key, click 'Continue' in the Revolut Business interface and press 'Enter' here to continue ...")
        input()
        add_to_log("You should now see a screen that contains the Client ID.")
        add_to_log("-> Enter the Client ID here and press 'Enter' to continue ...")
        client_id = input()
        # make sure that the client ID is entered correctly
        while len(client_id) < 5:
            add_to_log("The Client ID is too short. Please enter the Client ID correctly and press 'Enter' to continue ...")
            client_id = input()
        add_to_log("Next, lets create the JWT (JSON Web Token), to create new access tokens for accessing your account.")
        add_to_log("For how many days should the JWT be valid?")
        add_to_log("-> Press 'Enter' to use the default value of 90 days, or enter a different value and press 'Enter' to continue ...")
        expires_in_days = input()
        if expires_in_days == "":
            expires_in_days = 90
            add_to_log(f"Ok. Using the default value of {str(expires_in_days)} days expiration time.")
        else:
            expires_in_days = int(expires_in_days)


        # prepare the JWT header
        jwt_header = {
            "alg": "RS256",
            "typ": "JWT"
        }

        # prepare the payload
        jwt_payload = {
            "iss": redirect_uri,
            "sub": client_id,
            "aud": "https://revolut.com",
            "exp": int((datetime.now() + timedelta(days=expires_in_days)).timestamp())
        }

        # Encode the header
        header = json.dumps(jwt_header).encode()
        encoded_header = base64_url_encode(header)

        # Encode the payload
        payload = json.dumps(jwt_payload).encode()
        encoded_payload = base64_url_encode(payload)

        # Generate the signature
        signature = sign_with_private_key(encoded_header + b'.' + encoded_payload, f"{target_folder}/privatecert.pem")

        # Concatenate the parts
        client_assertion = encoded_header + b'.' + encoded_payload + b'.' + signature

        # save the client_assertion as a client_assertion.txt file
        with open(f"{target_folder}/client_assertion.txt", 'wb') as f:
            f.write(client_assertion)

        add_to_log("Next, click 'Enable access' in the Revolut Business interface and follow the instructions in Revolut.")
        add_to_log("At the end of the process, you will be forwarded to your redirect URI, including the authorization code.")
        add_to_log("-> Enter the full URL of the redirect URI here and press 'Enter' to continue ...")
        redirect_uri_with_auth_code = input()
        # make sure that the redirect URI is entered correctly
        while len(redirect_uri_with_auth_code) < 5:
            add_to_log("The redirect URI is too short. Please enter the redirect URI correctly and press 'Enter' to continue ...")
            redirect_uri_with_auth_code = input()
        # extract the authorization code from the redirect URI
        auth_code = re.sub('.*code=', '', redirect_uri_with_auth_code)

        # save the authorization code and JWT to the secrets file
        
        secrets["REVOLUT_BUSINESS_AUTH_CODE"] = auth_code
        secrets["REVOLUT_BUSINESS_JWT"] = client_assertion.decode()
        secrets["REVOLUT_BUSINESS_CLIENT_ID"] = client_id
        save_secrets(secrets)

        add_to_log(f"Successfully saved the authorization code, client ID and JWT to the secrets .env file", state="success")
        return True

    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to saved the authorization code, client ID and JWT", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    get_authcode_and_jwt()