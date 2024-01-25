################

# Default Imports

################
import sys
import os
import re
import requests

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.finance.banks.revolut_business.authentification.get_authcode_and_jwt import get_authcode_and_jwt
from datetime import datetime


def get_access_token(restart_auth_flow: bool = False, request_new_after_minutes: int = 30) -> str:
    try:
        add_to_log(module_name="Revolut Business", color="blue", state="start")
        add_to_log("Getting access token ...")

        secrets = load_secrets()

        access_token_last_updated_unix = secrets.get("REVOLUT_BUSINESS_ACCESS_TOKEN_LAST_UPDATED_UNIX")
        if access_token_last_updated_unix:
            access_token_last_updated_unix = int(access_token_last_updated_unix)

        # if restart_auth_flow is True, delete REVOLUT_BUSINESS_ACCESS_TOKEN_LAST_UPDATED_UNIX, REVOLUT_BUSINESS_AUTH_CODE and REVOLUT_BUSINESS_JWT
        # context: because of PSD2 SCA regulations, transactions older then 90 days can only be retrieved in the first 5 minutes of authorization of a new token
        if restart_auth_flow and not access_token_last_updated_unix or restart_auth_flow and (int(datetime.now().timestamp()) - access_token_last_updated_unix > 5 * 60):
            add_to_log("Because of PSD2 SCA regulations, transactions older then 90 days can only be retrieved in the first 5 minutes of authorization of a new token.")
            add_to_log("The current token however is older then 5 minutes. Therefore restarting the authorization flow ...")
            secrets["REVOLUT_BUSINESS_ACCESS_TOKEN_LAST_UPDATED_UNIX"] = ""
            secrets["REVOLUT_BUSINESS_ACCESS_TOKEN"] = ""
            secrets["REVOLUT_BUSINESS_AUTH_CODE"] = ""
            secrets["REVOLUT_BUSINESS_REFRESH_TOKEN"] = ""
            secrets["REVOLUT_BUSINESS_CLIENT_ID"] = ""
            secrets["REVOLUT_BUSINESS_JWT"] = ""
            save_secrets(secrets)

        # if the token is not expired, return it
        if access_token_last_updated_unix and (int(datetime.now().timestamp()) - access_token_last_updated_unix < request_new_after_minutes * 60):
            add_to_log("Access token is still valid. Returning it ...", state="success")
            return secrets["REVOLUT_BUSINESS_ACCESS_TOKEN"]

        # check if the auth code and JWT exist and are not set to ""
        while not secrets.get("REVOLUT_BUSINESS_AUTH_CODE") or not secrets.get("REVOLUT_BUSINESS_JWT"):
            add_to_log("Auth code and JWT not found. Starting the process to get them ...")
            get_authcode_and_jwt()
            secrets = load_secrets()
        
        url = "https://b2b.revolut.com/api/1.0/auth/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "authorization_code",
            "code": secrets["REVOLUT_BUSINESS_AUTH_CODE"],
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": secrets["REVOLUT_BUSINESS_JWT"]
        }

        if secrets.get("REVOLUT_BUSINESS_REFRESH_TOKEN"):
            data["grant_type"] = "refresh_token"
            data["refresh_token"] = secrets["REVOLUT_BUSINESS_REFRESH_TOKEN"]
        
        response = requests.post(url, headers=headers, data=data)
        if response.status_code != 200:
            process_error(f"Failed to get access token. Status code: {response.status_code}: {response.text}")
            return None
        
        response_json = response.json()
        secrets["REVOLUT_BUSINESS_ACCESS_TOKEN"] = response_json.get('access_token')
        secrets["REVOLUT_BUSINESS_ACCESS_TOKEN_LAST_UPDATED_UNIX"] = int(datetime.now().timestamp())
        if response_json.get('refresh_token'):
            secrets["REVOLUT_BUSINESS_REFRESH_TOKEN"] = response_json.get('refresh_token')

        # write the access token to the secrets file
        save_secrets(secrets)

        add_to_log(f"Successfully obtained new access token", state="success")
        return secrets["REVOLUT_BUSINESS_ACCESS_TOKEN"]
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to get access token", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    get_access_token()