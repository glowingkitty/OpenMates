################

# Default Imports

################
import sys
import os
import subprocess
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################


def generate_private_and_public_certificate() -> bool:
    try:
        add_to_log(module_name="Revolut Business", color="blue", state="start")
        add_to_log("Generating private and public certificates ...")

        target_folder = re.sub('OpenMates.*', 'OpenMates/my_profile/secrets/revolut_business', full_current_path)

        # Check if the files already exist
        if os.path.exists(f"{target_folder}/privatecert.pem") and os.path.exists(f"{target_folder}/publiccert.cer"):
            add_to_log("Private and public certificates already exist", state="success")
            return True

        # get the secrets
        secrets = load_secrets()
        country_code = secrets["REVOLUT_BUSINESS_CERTIFICATE_COUNTRY_CODE"]
        state_name = secrets["REVOLUT_BUSINESS_CERTIFICATE_STATE_NAME"]
        locality_name = secrets["REVOLUT_BUSINESS_CERTIFICATE_LOCALITY_NAME"]
        organization_name = secrets["REVOLUT_BUSINESS_CERTIFICATE_ORGANIZATION_NAME"]
        common_name = secrets["REVOLUT_BUSINESS_CERTIFICATE_COMMON_NAME"]
        email_address = secrets["REVOLUT_BUSINESS_CERTIFICATE_EMAIL_ADDRESS"]


        # Create the target folder if it does not exist
        os.makedirs(target_folder, exist_ok=True)
        
        # Define command to generate private key
        private_key_cmd = f"openssl genrsa -out {target_folder}/privatecert.pem 2048"
        # Execute the command
        subprocess.run(private_key_cmd, shell=True, check=True)

        # Define command to generate public certificate
        subj_str = f"/C={country_code}/ST={state_name}/L={locality_name}/O={organization_name}/CN={common_name}/emailAddress={email_address}"
        public_cert_cmd = f"openssl req -new -x509 -key {target_folder}/privatecert.pem -out {target_folder}/publiccert.cer -days 1825 -subj \"{subj_str}\""
        # Execute the command
        subprocess.run(public_cert_cmd, shell=True, check=True)
        
        add_to_log("Successfully generated private and public certificates", state="success")
        return True
    
    except subprocess.CalledProcessError as e:
        process_error(f"OpenSSL command failed with error: {e}", traceback=traceback.format_exc())
        return False
    except Exception:
        process_error("Failed to generate certificates", traceback=traceback.format_exc())
        return False
    
if __name__ == "__main__":
    generate_private_and_public_certificate()