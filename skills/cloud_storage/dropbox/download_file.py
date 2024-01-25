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


def download_file(filepath: str, target_folder:str = None) -> str:
    try:
        add_to_log(state="start", module_name="Cloud storage | Dropbox", color="blue")
        add_to_log(f"Prepare to download file from Dropbox ({filepath}) ...")

        # if no target_folder is given, use "{main_directory}/temp_data/cloud_storage"
        if not target_folder:
            target_folder = f"{main_directory}/temp_data/cloud_storage"

        # if target_folder does not exist, create it
        os.makedirs(target_folder, exist_ok=True)

        secrets = load_secrets()

        with dropbox.Dropbox(oauth2_refresh_token=secrets["DROPBOX_REFRESH_TOKEN"], app_key=secrets["DROPBOX_APP_KEY"]) as dbx:
            # Check if the file exists in Dropbox
            try:
                dbx.files_get_metadata(filepath)
            except dropbox.exceptions.ApiError as e:
                if isinstance(e.error, dropbox.files.GetMetadataError) and \
                        e.error.is_path():
                    raise FileNotFoundError(f"File not found in Dropbox ({filepath})")
                else:
                    raise e

            add_to_log(f"Downloading file from Dropbox ({filepath}) ...")
            # Download the file
            _, response = dbx.files_download(filepath)

            # Save the file to local system
            local_path = os.path.join(target_folder, os.path.basename(filepath))
            with open(local_path, 'wb') as f:
                f.write(response.content)

            add_to_log(state="success", message=f"File downloaded from Dropbox -> '{local_path}'")

        return local_path

    except dropbox.exceptions.AuthError:
        add_to_log("Access token expired. Retrieving a new one ...")
        get_refresh_token()
        return download_file(filepath)
    
    except FileNotFoundError:
        add_to_log(f"File not found in Dropbox ({filepath})",state="error")
        return None

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error(f"Failed to download file from Dropbox ({filepath})", traceback=traceback.format_exc())
        return None


if __name__ == "__main__":
    filepath = "/Documents/Finance/Vouchers/process_these_vouchers/invoice.pdf"
    download_file(filepath)