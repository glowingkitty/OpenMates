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


def get_duplicates_files(cloud_filepath: str, cloud_folderpath_to_compare: str) -> list:
    try:
        add_to_log(module_name="Cloud storage | Dropbox", color="blue", state="start")
        add_to_log(f"Checking if there are any duplicates for '{cloud_filepath}' in '{cloud_folderpath_to_compare}' ...")

        # Load Dropbox access token from secrets
        secrets = load_secrets()
        with dropbox.Dropbox(oauth2_refresh_token=secrets["DROPBOX_REFRESH_TOKEN"], app_key=secrets["DROPBOX_APP_KEY"]) as dbx:
            # Get the content hash of the input file
            input_file_metadata = dbx.files_get_metadata(cloud_filepath)
            input_file_hash = input_file_metadata.content_hash

            # Get a list of all files in the cloud_folderpath_to_compare and its subdirectories
            all_files_metadata = dbx.files_list_folder(cloud_folderpath_to_compare, recursive=True).entries

            # Find files with the same content hash
            duplicate_files = [file_metadata.path_lower for file_metadata in all_files_metadata if isinstance(file_metadata, dropbox.files.FileMetadata) and file_metadata.content_hash == input_file_hash and file_metadata.path_lower != cloud_filepath.lower()]

        add_to_log(f"Found {len(duplicate_files)} duplicate file(s) for: {cloud_filepath}", state="success")
        return duplicate_files

    except dropbox.exceptions.ApiError:
        add_to_log(f"File does not exist: {cloud_filepath}", state="error")
        return []

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error(f"Failed to check for duplicate files: '{cloud_filepath}'", traceback=traceback.format_exc())
        return []

if __name__ == "__main__":
    duplicates = get_duplicates_files(cloud_filepath="/Documents/Finance/Vouchers/process_these_vouchers/test.txt")
    print(duplicates)