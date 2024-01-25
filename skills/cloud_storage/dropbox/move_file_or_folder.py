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


def move_file_or_folder(from_filepath: str, to_filepath: str) -> str:
    try:
        add_to_log(state="start", module_name="Cloud storage | Dropbox", color="blue")
        add_to_log(f"Prepare to move file or folder in Dropbox from {from_filepath} to {to_filepath} ...")

        secrets = load_secrets()

        with dropbox.Dropbox(oauth2_refresh_token=secrets["DROPBOX_REFRESH_TOKEN"], app_key=secrets["DROPBOX_APP_KEY"]) as dbx:
            # Check if the file or folder exists in Dropbox
            try:
                dbx.files_get_metadata(from_filepath)
            except dropbox.exceptions.ApiError as e:
                if isinstance(e.error, dropbox.files.GetMetadataError) and \
                        e.error.is_path():
                    raise FileNotFoundError(f"File or folder not found in Dropbox ({from_filepath})")
                else:
                    raise e
                
            # if to_filepath does not end with '/' and has no file extension, add '/' to the end
            if to_filepath.endswith('/') and not to_filepath.endswith(os.path.basename(from_filepath) + '/'):
                to_filepath = os.path.join(to_filepath, os.path.basename(from_filepath))

            # If to_filepath is a directory and doesn't already contain the filename, append the filename from from_filepath
            if to_filepath.endswith('/') and os.path.basename(from_filepath) not in to_filepath:
                to_filepath = os.path.join(to_filepath, os.path.basename(from_filepath))

            # Check if the destination folder exists, if not create it
            destination_folder = os.path.dirname(to_filepath)
            try:
                dbx.files_get_metadata(destination_folder)
            except dropbox.exceptions.ApiError as e:
                if isinstance(e.error, dropbox.files.GetMetadataError) and \
                        e.error.is_path():
                    dbx.files_create_folder_v2(destination_folder)

            add_to_log(f"Moving file or folder in Dropbox from {from_filepath} to {to_filepath} ...")
            # Move the file or folder
            entries = [dropbox.files.RelocationPath(from_path=from_filepath, to_path=to_filepath)]
            dbx.files_move_batch(entries)

            add_to_log(state="success", message=f"File or folder moved in Dropbox -> from '{from_filepath}' to '{to_filepath}'")

        return to_filepath

    except dropbox.exceptions.AuthError:
        add_to_log("Access token expired. Retrieving a new one ...")
        get_refresh_token()
        return move_file_or_folder(from_filepath, to_filepath)
    
    except FileNotFoundError:
        add_to_log(f"File or folder not found in Dropbox ({from_filepath})",state="error")
        return False

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error(f"Failed to move file or folder in Dropbox from {from_filepath} to {to_filepath}", traceback=traceback.format_exc())
        return False
    
if __name__ == "__main__":
    move_file_or_folder("/Documents/Finance/Vouchers/process_these_vouchers/test", "/Documents/Finance/Vouchers/2023/2023_04")