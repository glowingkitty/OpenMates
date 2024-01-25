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
from dropbox.sharing import CreateSharedLinkWithSettingsError


def upload_file(
        filepath: str, 
        target_path: str = None,
        raw_url: bool = False,
        delete_original: bool = False,
        share_file: bool = False
        ) -> str:
    try:
        add_to_log(state="start", module_name="Cloud storage | Dropbox", color="blue")
        add_to_log(f"Prepare to upload file to Dropbox ({filepath}) ...")

        config = load_config()
        secrets = load_secrets()
        shared_url = None
        dropbox_filepath = None

        # load target_path from config
        if target_path is None:
            # get the config for Dropbox (go over the list of dicts in config["modules"]["cloud_storage"])
            dropbox_config = None
            for module in config["modules"]["cloud_storage"]["all_available"]:
                if module["source"] == "Dropbox":
                    dropbox_config = module
                    break
            if dropbox_config["default_target"]:
                target_path = dropbox_config["default_target"]
            else:
                add_to_log(f"No default_target_folder found for Dropbox. Using '/api_uploads/OpenMates/' instead.")
                target_path = "/api_uploads/OpenMates/"

        
        # check if the file exists
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found ({filepath})")
        
        add_to_log(f"Uploading file to Dropbox (from '{filepath}' to '{target_path}')...")
        with dropbox.Dropbox(oauth2_refresh_token=secrets["DROPBOX_REFRESH_TOKEN"], app_key=secrets["DROPBOX_APP_KEY"]) as dbx:

            with open(filepath, 'rb') as f:
                if not re.search(r'\.\w+$', target_path):
                    target_path = os.path.join(target_path, os.path.basename(filepath))
                add_to_log(f"target_path: {target_path}) ...")
                dbx.files_upload(f.read(), target_path, mode=dropbox.files.WriteMode.overwrite)

            add_to_log(state="success", message=f"File uploaded to Dropbox -> '{target_path}'")

            dropbox_filepath = target_path

            if share_file:
                add_to_log(f"Sharing the file -> '{target_path}' ...")
                try:
                    link = dbx.sharing_create_shared_link_with_settings(target_path + os.path.basename(filepath))
                    shared_url = link.shared_url
                    if raw_url:
                        shared_url = shared_url.replace('&dl=0', '&raw=1')
                    
                    add_to_log(state="success", message=f"Shared the file -> '{shared_url}'")
                    
                except dropbox.exceptions.ApiError as e:
                    if isinstance(e.error, CreateSharedLinkWithSettingsError) and \
                            e.error.is_shared_link_already_exists():
                        # Get the shared link
                        link = dbx.sharing_list_shared_links(target_path + os.path.basename(filepath)).links[0]
                        shared_url = link.shared_url
                        if raw_url:
                            shared_url = shared_url.replace('&dl=0', '&raw=1')
                        
                        add_to_log(state="success", message=f"File was already shared -> '{shared_url}'")
                    else:
                        raise e
                
            if delete_original:
                os.remove(filepath)

        return {
            "dropbox_filepath": dropbox_filepath,
            "shared_url": shared_url
        }
    
    except dropbox.exceptions.AuthError:
        add_to_log("Access token expired. Retrieving a new one ...")
        get_refresh_token()
        return upload_file(filepath, target_path, raw_url, delete_original)

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error(f"Failed to upload file to Dropbox ({filepath})", traceback=traceback.format_exc())
        return None
    

if __name__ == "__main__":
    filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)), "test.txt")
    upload_file(filepath, target_path="/Documents/Finance/Vouchers/process_these_vouchers")