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


import base64
from googleapiclient.discovery import build
from email.mime.text import MIMEText
from skills.email.googlemail.get_credentials import get_credentials


def create_email_draft(message:str = None, subject: str = None, to_email:str = None, is_html:bool=False) -> str:
    try:
        add_to_log(module_name="Email | Google Mail", color="yellow", state="start")
        add_to_log("Preparing to save email draft ...")

        # at least one of the parameters must be set
        if not message and not subject and not to_email:
            raise ValueError("At least one of the parameters must be set.")

        # Load the credentials from the file
        creds = get_credentials()

        add_to_log("Creating email draft ...")
        service = build('gmail', 'v1', credentials=creds)

        # Create the email message
        email_message = MIMEText(message, 'html' if is_html else 'plain')
        email_message['to'] = to_email
        email_message['subject'] = subject
        raw_message = base64.urlsafe_b64encode(email_message.as_bytes())
        raw_message = raw_message.decode()
        body = {'message': {'raw': raw_message}}  # Add 'message' field

        # Create the draft
        draft = service.users().drafts().create(userId='me', body=body).execute()

        add_to_log(f"Successfully created email draft with ID: {draft['id']}", state="success")
        return draft['id']

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to create an email draft.", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    create_email_draft(message="Hello World!", subject="Test")
