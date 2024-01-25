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

from skills.cloud_storage.dropbox.get_files_in_folder import get_files_in_folder
from skills.cloud_storage.dropbox.get_duplicate_files import get_duplicates_files
from skills.cloud_storage.dropbox.delete_file_or_folder import delete_file_or_folder


def delete_all_duplicates(cloud_folderpath_to_process: str, cloud_folderpath_to_compare: str) -> bool:
    try:
        add_to_log(module_name="Cloud storage | Dropbox", color="blue", state="start")
        add_to_log(f"Preparing to delete all duplicate files in the folder '{cloud_folderpath_to_process}' ...")

        # get a list of all files in the folder
        files = get_files_in_folder(folderpath=cloud_folderpath_to_process)
        
        # for every file in the folder, check if there are duplicates in the other folder
        for file in files:
            # get a list of all duplicates
            duplicates = get_duplicates_files(cloud_filepath=file["path"], cloud_folderpath_to_compare=cloud_folderpath_to_compare)
            if len(duplicates) > 0:
                add_to_log(f"Deleting {len(duplicates)} duplicate file(s) for: {file['name']}")
                add_to_log(f"Duplicate files: {duplicates}")
                input("Press Enter to delete them...")
                # delete all duplicates
                for duplicate in duplicates:
                    delete_file_or_folder(filepath=duplicate)


    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error(f"Failed to delete all duplicate files in the folder '{cloud_folderpath_to_process}'", traceback=traceback.format_exc())
        return []

if __name__ == "__main__":
    delete_all_duplicates(cloud_folderpath_to_process="/Documents/Finance/Vouchers/Expenses", cloud_folderpath_to_compare="/Documents/Finance/Vouchers")