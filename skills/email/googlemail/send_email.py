################

# Default Imports

################
import sys
import os
import re
import traceback

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

from googleapiclient.discovery import build
from skills.email.googlemail.get_credentials import get_credentials

def send_email(email_id: str) -> bool:
    try:
        add_to_log(module_name="Email | Google Mail", color="yellow", state="start")
        add_to_log("Preparing to send email ...")

        # Load the credentials from the file
        creds = get_credentials()

        add_to_log("Sending email ...")
        service = build('gmail', 'v1', credentials=creds)

        # Get the draft
        draft = service.users().drafts().get(userId='me', id=email_id).execute()

        # Send the draft
        sent_message = service.users().drafts().send(userId='me', body=draft).execute()

        add_to_log(f"Successfully sent email with ID: {sent_message['id']}", state="success")
        return True

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to send an email.", traceback=traceback.format_exc())
        return False

if __name__ == "__main__":
    send_email("r6537883910405648367")