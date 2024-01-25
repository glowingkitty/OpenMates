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

from skills.cloud_storage.dropbox.authentification.get_refresh_token import get_refresh_token 
import dropbox


def delete_file_or_folder(filepath: str, delete_folder_if_empty: bool = False) -> bool:
    try:
        add_to_log(state="start", module_name="Cloud storage | Dropbox", color="blue")
        add_to_log(f"Prepare to delete file or folder from Dropbox ({filepath}) ...")

        secrets = load_secrets()

        with dropbox.Dropbox(oauth2_refresh_token=secrets["DROPBOX_REFRESH_TOKEN"], app_key=secrets["DROPBOX_APP_KEY"]) as dbx:
            # Check if the file or folder exists in Dropbox
            try:
                metadata = dbx.files_get_metadata(filepath)
            except dropbox.exceptions.ApiError as e:
                if isinstance(e.error, dropbox.files.GetMetadataError) and \
                        e.error.is_path():
                    raise FileNotFoundError(f"File or folder not found in Dropbox ({filepath})")
                else:
                    raise e

            if delete_folder_if_empty and isinstance(metadata, dropbox.files.FolderMetadata):
                # Check if the folder is empty
                result = dbx.files_list_folder(filepath)
                if len(result.entries) > 0:
                    add_to_log(f"Folder in Dropbox ({filepath}) is not empty. Skipping deletion.")
                    return False

            add_to_log(f"Deleting file or folder from Dropbox ({filepath}) ...")
            # Delete the file or folder
            dbx.files_delete_v2(filepath)

            add_to_log(state="success", message=f"File or folder deleted from Dropbox -> '{filepath}'")

        return True

    except dropbox.exceptions.AuthError:
        add_to_log("Access token expired. Retrieving a new one ...")
        get_refresh_token()
        return delete_file_or_folder(filepath, delete_folder_if_empty)
    
    except FileNotFoundError:
        add_to_log(f"File or folder not found in Dropbox ({filepath})",state="error")
        return False

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error(f"Failed to delete file or folder from Dropbox ({filepath})", traceback=traceback.format_exc())
        return False
    

if __name__ == "__main__":
    delete_file_or_folder("/Documents/Finance/Vouchers/process_these_vouchers/testfolder", delete_folder_if_empty=True)