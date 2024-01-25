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

import dropbox
from skills.cloud_storage.dropbox.authentification.get_refresh_token import get_refresh_token


def get_files_in_folder(folderpath: str = "/api_uploads/OpenMates", fileextensions: list = None) -> list:
    try:
        add_to_log(module_name="Cloud storage | Dropbox", color="blue", state="start")
        add_to_log("Retrieving list of files and folders ...")

        # Load Dropbox access token from secrets
        secrets = load_secrets()
        with dropbox.Dropbox(oauth2_refresh_token=secrets["DROPBOX_REFRESH_TOKEN"], app_key=secrets["DROPBOX_APP_KEY"]) as dbx:
            # List folder contents
            folder_items = []
            for entry in dbx.files_list_folder(folderpath).entries:
                if isinstance(entry, dropbox.files.FolderMetadata):
                    folder_items.extend(get_files_in_folder(entry.path_display, fileextensions))
                else:
                    # Check if file extension is in the provided list
                    if fileextensions is None or os.path.splitext(entry.name)[1][1:].lstrip('.') in [ext.lstrip('.') for ext in fileextensions]:
                        metadata = {
                            "path": entry.path_display,
                            "name": entry.name,
                            "last_modified": entry.client_modified
                        }
                        folder_items.append(metadata)
            
        add_to_log(f"Successfully retrieved folder content: {len(folder_items)} item{'s' if len(folder_items)>1 else ''}", state="success")
        return folder_items
    
    except dropbox.exceptions.AuthError:
        add_to_log("Access token expired. Retrieving a new one ...")
        get_refresh_token()
        return get_files_in_folder(folderpath, fileextensions)
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to get folder contents for '{folderpath}'", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    directory = get_files_in_folder("/Documents/Finance/Vouchers/process_these_vouchers")
    print(directory)
