################

# Default Imports

################
import sys
import os
import re


# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
OpenMates_directory = re.sub('OpenMates.*', 'OpenMates', full_current_path)
sys.path.append(main_directory)
from server import *
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.credentials import Credentials


################


def get_credentials() -> Credentials:
    try:
        add_to_log(module_name="Email | Google Mail", color="yellow", state="start")
        add_to_log("Getting credentials ...")

        # Load the credentials from the file
        creds = None
        if os.path.exists(f"{OpenMates_directory}/my_profile/secrets/google/token.pickle"):
            with open(f"{OpenMates_directory}/my_profile/secrets/google/token.pickle", 'rb') as token:
                creds = pickle.load(token)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    client_secrets_file=f"{OpenMates_directory}/my_profile/secrets/google/credentials.json", 
                    scopes=[
                        'https://www.googleapis.com/auth/gmail.readonly',
                        'https://www.googleapis.com/auth/gmail.compose'
                        ]
                    )
                creds = flow.run_local_server(port=0)
            with open(f"{OpenMates_directory}/my_profile/secrets/google/token.pickle", 'wb') as token:
                pickle.dump(creds, token)

        add_to_log("Successfully got credentials.", state="success")

        return creds

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to get credentials")
        return None

if __name__ == "__main__":
    get_credentials()