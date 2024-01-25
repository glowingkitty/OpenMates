################

# Default Imports

################
import sys
import os
import re
import requests
import json

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.finance.accounting.sevdesk.contact.get_contacts import get_contacts

def search_contact(
        surename: str = None, 
        familyname: str = None, 
        name: str = None
        ) -> dict:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Search contact in SevDesk ...")

        if not surename and not familyname and not name:
            add_to_log("Please provide at least one of the following: surename, familyname, name", state="error")
            return None
        
        all_contacts = get_contacts()

        # search for the contact
        for contact in all_contacts:
            if surename and familyname and contact["surename"] == surename and contact["familyname"] == familyname:
                add_to_log(f"Found contact by surename and familyname.", state="success")
                return contact
            elif surename and contact["surename"] == surename:
                add_to_log(f"Found contact by surename.", state="success")
                return contact
            elif name and contact["name"] == name:
                add_to_log(f"Found contact by name.", state="success")
                return contact
        
        add_to_log(f"Finished search. But could not find an existing contact", state="success")
        return None
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception as e:
        process_error(f"Failed to find contact.", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    contact = search_contact(surename="Vorname")
    # save the contact to a file
    if contact:
        with open("found_contact.json", "w") as f:
            json.dump(contact, f, indent=4)
        print("found_contact.json")