################

# Default Imports

################
import sys
import os
import re
import base64
from googleapiclient.discovery import build

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.email.googlemail.get_credentials import get_credentials
import email
import pdfkit
import unicodedata


def email_to_pdf(
        email_id: str,
        folderpath: str = None,
        also_save_attachments: bool = True
        ) -> list:
    try:
        add_to_log(module_name="Email | Google Mail", color="yellow", state="start")
        add_to_log("Converting email to PDF ...")
        

        # Load credentials and build the service
        creds = get_credentials()
        service = build('gmail', 'v1', credentials=creds)

        # Get the email message
        message = service.users().messages().get(userId='me', id=email_id, format='raw').execute()
        msg_str = base64.urlsafe_b64decode(message['raw'].encode('ASCII')).decode('utf-8', 'ignore')

        # Parse the email content
        msg = email.message_from_string(msg_str)
        body = ""

        # Get the email body
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    body = part.get_payload(decode=True)
                    body = body.decode('utf-8', errors='ignore')
                    break
                elif part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True)
                    body = body.decode('utf-8', errors='ignore')
        else:
            body = msg.get_payload(decode=True)
            body = body.decode('utf-8', errors='ignore')

        # Normalize unicode characters
        body = unicodedata.normalize("NFC", body)

        # Define PDF path
        if not folderpath:
            folderpath = f"{main_directory}temp_data/emails"

        # create folder if it does not exist
        os.makedirs(folderpath, exist_ok=True)

        pdf_path = os.path.join(folderpath, f'email_{email_id}.pdf')

        # Convert HTML to PDF
        try:
            pdfkit.from_string(body, pdf_path)
        except OSError as e:
            if 'Exit with code 1 due to network error: ContentOperationNotPermittedError' in str(e):
                add_to_log("Network error occurred while converting email to PDF.", state="error")
            else:
                add_to_log(f"An error occurred while converting email to PDF: {e}", state="error")

        file_paths = [pdf_path]

        # Save attachments if also_save_attachments is True
        if also_save_attachments:
            for part in msg.walk():
                if part.get_content_disposition() == 'attachment':
                    filename = part.get_filename()
                    if filename:
                        attachment_path = os.path.join(folderpath, filename)
                        with open(attachment_path, 'wb') as f:
                            f.write(part.get_payload(decode=True))
                        file_paths.append(attachment_path)

        if len(file_paths) > 1:
            add_to_log(f"Successfully converted email to PDF and saved attachments.", state="success")
            add_to_log(f"Email: {pdf_path}", state="success")
            add_to_log(f"Attachments:", state="success")
            for file_path in file_paths[1:]:
                add_to_log(file_path, state="success")
        else:
            add_to_log(f"Successfully converted email to PDF: {pdf_path}", state="success")
        return pdf_path

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to convert email to PDF", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    email_to_pdf("18c2e81132d22760")