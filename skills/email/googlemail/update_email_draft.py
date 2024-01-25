
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
from email import message_from_string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from skills.email.googlemail.get_credentials import get_credentials


def update_email_draft(email_id: str, message: str = None, subject: str = None, to_email: str = None, is_html: bool = False) -> bool:
    try:
        add_to_log(module_name="Email | Google Mail", color="yellow", state="start")
        add_to_log("Preparing to update email draft ...")

        # Load the credentials from the file
        creds = get_credentials()

        add_to_log("Updating email draft ...")
        service = build('gmail', 'v1', credentials=creds)

        # Fetch the existing draft
        draft = service.users().drafts().get(userId='me', id=email_id, format='raw').execute()
        raw_message = base64.urlsafe_b64decode(draft['message']['raw']).decode()
        email_message = message_from_string(raw_message)

        # Check which fields are provided and update those fields
        if to_email is not None:
            email_message.replace_header('To', to_email)
        if subject is not None:
            email_message.replace_header('Subject', subject)
        if message is not None:
            mime_text = MIMEText(message, 'html' if is_html else 'plain')
            if email_message.is_multipart():
                email_message.attach(mime_text)
            else:
                email_message.set_payload(mime_text.get_payload())

        # Re-encode the message
        raw_message = base64.urlsafe_b64encode(email_message.as_bytes()).decode()
        body = {'message': {'raw': raw_message}}  # Add 'message' field

        # Update the draft
        draft = service.users().drafts().update(userId='me', id=email_id, body=body).execute()

        add_to_log(f"Successfully updated email draft with ID: {draft['id']}", state="success")
        return True

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to update an email draft.", traceback=traceback.format_exc())
        return False

if __name__ == "__main__":
    update_email_draft(email_id="r8902934494613991957", subject="hello!")