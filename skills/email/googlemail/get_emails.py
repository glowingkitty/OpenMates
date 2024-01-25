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
from datetime import datetime
import base64
from googleapiclient.discovery import build

import json
import copy
from email.utils import parseaddr
from datetime import datetime

################

from skills.email.googlemail.get_credentials import get_credentials
from skills.email.googlemail.email_to_pdf import email_to_pdf
from skills.finance.accounting.search_in_pdf_file_and_name import search_in_pdf_file_and_name
from datetime import timedelta

def get_emails(
        text_contains: str = None,
        attachments_filetypes: list = None, 
        attachments_filenames_contain: list = None,
        pdf_text_search_variations: list = None,
        from_date: str = None, 
        to_date: str = None,
        filter_for: str = None,
        timezone: str = "+01:00", # based on UTC
        save_emails: bool = False,
        save_to_json: bool = False,
        num_results: int = 100,
        transaction: dict = None, # if a transaction is given, the emails and pdfs related to the transaction will be searched
        ) -> list:
    try:
        add_to_log(module_name="Email | Google Mail", color="yellow", state="start")
        add_to_log("Preparing to fetch emails ...")

        # Call the Gmail API
        query = ""

        # If a transaction is given, get the search parameters from the transaction
        if transaction:
            # parse the entryDate from the transaction and set the from_date to 7 days before and the to_date to 7 days after
            entryDate = datetime.strptime(transaction['entryDate'], '%Y-%m-%dT%H:%M:%S%z')
            from_date = (entryDate - timedelta(days=7)).strftime('%Y/%m/%d')
            to_date = (entryDate + timedelta(days=7)).strftime('%Y/%m/%d')


        ###########################
        #### Search for emails ####
        ###########################

        # Load the credentials from the file
        creds = get_credentials()

        add_to_log("Fetching emails ...")
        service = build('gmail', 'v1', credentials=creds)


        # if to_date is equal to from_date, add one day to to_date
        if from_date == to_date:
            to_date = datetime.strptime(to_date, '%Y/%m/%d')
            to_date += timedelta(days=1)
            to_date = to_date.strftime('%Y/%m/%d')
            
        if text_contains:
            query += text_contains
        if from_date:
            try:
                # testing if the date is in the correct format, if yes, continue, else return error
                datetime.strptime(from_date, '%Y/%m/%d')
                query += f" after:{from_date}"
            except ValueError:
                return "Error: from_date must be in the format YYYY/MM/DD"
        if to_date:
            try:
                # testing if the date is in the correct format, if yes, continue, else return error
                datetime.strptime(to_date, '%Y/%m/%d')
                query += f" before:{to_date}"
            except ValueError:
                return "Error: to_date must be in the format YYYY/MM/DD"
            
        if filter_for == "incoming":
            query += " in:inbox"
        elif filter_for == "unread":
            query += " is:unread in:inbox"
        elif filter_for == "outgoing":
            query += " in:sent"

        # if the query starts with " ", remove it
        if query.startswith(" "):
            query = query[1:]
        
        add_to_log(f"Searching for emails with query: {query}")
        results = service.users().messages().list(userId='me', q=query, maxResults=num_results).execute()
        messages = results.get('messages', [])
        add_to_log(f"Found {len(messages)} emails with query: {query}")


        #######################################
        ###### Prepare emails for output ######
        #######################################

        emails = []
        for message in messages:

            msg = service.users().messages().get(userId='me', id=message['id']).execute()
            payload = msg['payload']
            headers = payload.get('headers')
            parts = payload.get('parts')
            email_data = {
                'id': message['id'],
                'sender': {'name': None, 'email_address': None},
                'datetime': datetime.fromtimestamp(int(msg.get('internalDate'))/1000).strftime('%Y-%m-%d %H:%M:%S '+timezone),
                'subject': None,
                'snippet': msg.get('snippet'),
                'unixtime': int(msg.get('internalDate'))/1000,
                'attachments': []
            }

            if headers:
                for header in headers:
                    name = header['name'].lower()
                    if name == 'from':
                        sender_name, sender_email = parseaddr(header['value'])
                        email_data['sender']['name'] = sender_name
                        email_data['sender']['email_address'] = sender_email
                    elif name == 'subject':
                        email_data['subject'] = header['value']

            at_least_one_pdf_contains_requested_text = False
            at_least_one_file_matches_requirements = False

            if parts:
                for part in parts:
                    this_pdf_contains_requested_text = False
                    if part.get('filename') and part.get('body').get('attachmentId'):
                        pdf_filepath = None
                        file_ending = part['filename'].split(".")[-1]
                        attachment_id = part['body']['attachmentId']
                        attachment = service.users().messages().attachments().get(userId='me', messageId=message['id'], id=attachment_id).execute()
                        file_data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))


                        #######################################
                        ########## Filter out emails ##########
                        #######################################
                        if attachments_filetypes and file_ending not in attachments_filetypes:
                            continue
                        if attachments_filenames_contain and not any(substr in part.get('filename') for substr in attachments_filenames_contain):
                            continue

                        if (pdf_text_search_variations or transaction) and part.get('filename').endswith(".pdf"):
                            # download the pdf, then search it just as locally stored pdfs are searched
                            pdf_filepath = f"{main_directory}temp_data/email_attachments/{part.get('filename')}"
                            # create the folder if it does not exist
                            os.makedirs(os.path.dirname(pdf_filepath), exist_ok=True)
                            with open(pdf_filepath, "wb") as f:
                                f.write(file_data)
                            
                            # search for the matching voucher
                            found_pdf = search_in_pdf_file_and_name(
                                search_variations=pdf_text_search_variations,
                                transaction=transaction, 
                                file_paths=[pdf_filepath]
                                )
                            if found_pdf:
                                this_pdf_contains_requested_text = True
                                at_least_one_pdf_contains_requested_text = True
                            else:
                                # if the PDF text does not contain any of the keywords, delete the pdf
                                os.remove(pdf_filepath)

                            # If the PDF text does not contain any of the keywords, skip this attachment
                            if not this_pdf_contains_requested_text:
                                continue

                        at_least_one_file_matches_requirements = True
                        
                        email_data['attachments'].append({
                            'filename': part.get('filename'),
                            'filepath': pdf_filepath
                        })

            # Filter out emails
            if attachments_filetypes or attachments_filenames_contain or pdf_text_search_variations or transaction:
                if not at_least_one_file_matches_requirements:
                    continue
            if  (pdf_text_search_variations or transaction) and not at_least_one_pdf_contains_requested_text:
                continue

            if attachments_filetypes and not email_data['attachments']:
                continue

            emails.append(email_data)

            if save_emails:
                email_to_pdf(
                    email_id=message['id'], 
                    folderpath=f"{main_directory}temp_data/emails/{message['id']}", 
                    also_save_attachments=True
                    )

        # save the data from the emails  to a json file, exclude the data key from the attachments
        if save_to_json == True:
            emails_for_json = []
            for email in emails:
                email_for_json = copy.deepcopy(email)
                emails_for_json.append(email_for_json)

            with open('emails.json', 'w') as f:
                json.dump(emails_for_json, f, indent=4)

        add_to_log(f"Successfully fetched emails: {len(emails)}", state="success")
        return emails

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to fetch emails", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    transaction = {
    }
    emails = get_emails(
        # transaction=transaction
        pdf_text_search_variations=[['11.57'],['11,57']],
        from_date="2023/09/09",
        to_date="2023/09/23",
        # save_to_json=True,
        )
    
    print(emails)