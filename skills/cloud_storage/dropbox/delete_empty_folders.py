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


def delete_empty_folders(path: str) -> bool:
    try:
        add_to_log(state="start", module_name="Cloud storage | Dropbox", color="blue")
        add_to_log(f"Prepare to delete empty folders from Dropbox ({path}) ...")

        secrets = load_secrets()

        path = os.path.normpath(path)

        with dropbox.Dropbox(oauth2_refresh_token=secrets["DROPBOX_REFRESH_TOKEN"], app_key=secrets["DROPBOX_APP_KEY"]) as dbx:
            # Check if the path exists in Dropbox
            try:
                metadata = dbx.files_get_metadata(path)
            except dropbox.exceptions.ApiError as e:
                if isinstance(e.error, dropbox.files.GetMetadataError) and \
                        e.error.is_path():
                    raise FileNotFoundError(f"Path not found in Dropbox ({path})")
                else:
                    raise e

            if isinstance(metadata, dropbox.files.FolderMetadata):
                # Recursively check all subfolders for files
                result = dbx.files_list_folder(path, recursive=True)

                # Create a list of all folders
                folders = [entry for entry in result.entries if isinstance(entry, dropbox.files.FolderMetadata)]

                # Check each folder separately
                for folder in folders:
                    # Skip the path folder itself
                    if folder.path_lower == path.lower():
                        continue

                    try:
                        folder_result = dbx.files_list_folder(folder.path_lower, recursive=True)
                    except dropbox.exceptions.ApiError as e:
                        if isinstance(e.error, dropbox.files.ListFolderError) and \
                                e.error.is_path() and \
                                isinstance(e.error.get_path(), dropbox.files.LookupError) and \
                                e.error.get_path().is_not_found():
                            add_to_log(f"Folder in Dropbox ({folder.path_lower}) not found. Skipping.")
                            continue
                        else:
                            raise e

                    if any(isinstance(entry, dropbox.files.FileMetadata) for entry in folder_result.entries):
                        add_to_log(f"Folder in Dropbox ({folder.path_lower}) contains files. Skipping deletion.")
                    else:
                        add_to_log(f"Deleting empty folder from Dropbox ({folder.path_lower}) ...")
                        dbx.files_delete_v2(folder.path_lower)

                add_to_log(state="success", message=f"Empty folders deleted from Dropbox -> '{path}'")

        return True

    except dropbox.exceptions.AuthError:
        add_to_log("Access token expired. Retrieving a new one ...")
        get_refresh_token()
        return delete_empty_folders(path)
    
    except FileNotFoundError:
        add_to_log(f"Path not found in Dropbox ({path})",state="error")
        return False

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error(f"Failed to delete empty folders from Dropbox ({path})", traceback=traceback.format_exc())
        return False
    

if __name__ == "__main__":
    delete_empty_folders("/Documents/Finance/Vouchers/process_these_vouchers")