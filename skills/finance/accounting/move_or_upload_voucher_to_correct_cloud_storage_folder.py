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

from skills.cloud_storage.dropbox.upload_file import upload_file
from skills.cloud_storage.dropbox.move_file_or_folder import move_file_or_folder


def move_or_upload_voucher_to_correct_cloud_storage_folder(
        voucher_data: dict,
        voucher_filepath_local: str,
        voucher_filepath_cloud: str
        ) -> str:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Moving or uploading voucher to correct cloud storage folder ...")

        # get the target folder from the voucher data
        if voucher_data and voucher_data.get("voucher"):
            # rename the file to the optimized filename
            if voucher_data["voucher"].get("optimized_filename"):
                add_to_log("Renaming the file on dropbox also to the optimized filename ...")
                filename = voucher_data["voucher"]["optimized_filename"]
        
                # then, if the voucher is not uploaded yet to cloud storage, upload it to the target folder
                if not voucher_filepath_cloud:
                    add_to_log("Uploading voucher to correct cloud storage folder ...")
                    # upload the file to dropbox
                    voucher_filepath_cloud = upload_file(
                        filepath=voucher_filepath_local, 
                        target_path=f"/Documents/Finance/Vouchers/{voucher_data['voucher']['target_folder']}/{filename}",
                        delete_original=True
                        )["dropbox_filepath"]
                
                else:
                    # if already uploaded, move it to the target folder
                    add_to_log("Moving voucher to correct cloud storage folder ...")
                    voucher_filepath_cloud = move_file_or_folder(
                        from_filepath=voucher_filepath_cloud, 
                        to_filepath=f"/Documents/Finance/Vouchers/{voucher_data['voucher']['target_folder']}/{filename}"
                        )

                if voucher_filepath_cloud:
                    add_to_log("Successfully moved or uploaded voucher to correct cloud storage folder", state="success")
                    return voucher_filepath_cloud
            
        add_to_log("Failed to move or upload voucher to correct cloud storage folder", state="error")
        return None

    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error("Failed to move or upload voucher to correct cloud storage folder", traceback=traceback.format_exc())
        return None