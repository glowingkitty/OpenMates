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

from skills.finance.accounting.search_in_pdf_file_and_name import search_in_pdf_file_and_name
from skills.finance.accounting.enrich_transaction_data import enrich_transaction_data


def search_vouchers_locally(transaction: dict, folder_path: str) -> bool:
    try:
        add_to_log(module_name="Finance", color="blue", state="start")
        add_to_log("Searching for voucher in locally stored files...")

        # get all files in folder_path and all files in all subfolders
        file_paths = []
        for (dirpath, dirnames, filenames) in os.walk(folder_path):
            for filename in filenames:
                if filename.endswith(".pdf"):
                    file_paths.append(os.path.join(dirpath, filename))

        # search for the matching voucher
        found_vouchers = search_in_pdf_file_and_name(transaction=transaction, file_paths=file_paths)
        add_to_log(f"Found {len(found_vouchers)} matching vouchers in locally stored files.", module_name="Finance")
        add_to_log(f"Found vouchers: {found_vouchers}", module_name="Finance")
            

        # if only one voucher was found, use it
        if len(found_vouchers) == 1:
            add_to_log(f"Successfully found a single voucher in locally stored files ({found_vouchers[0]})", module_name="Finance", state="success")
            local_filepath = found_vouchers[0]
            # get the cloud filepath
            if 'cloud_storage/voucher_pdfs/' in local_filepath:
                cloud_filepath = local_filepath.split('cloud_storage/voucher_pdfs')[1]
            elif 'temp_data/cloud_storage/' in local_filepath:
                cloud_filepath = local_filepath.split('temp_data/cloud_storage')[1]
            elif '/Dropbox/' in local_filepath:
                cloud_filepath = local_filepath.split('/Dropbox')[1]
            else:
                cloud_filepath = local_filepath
            return local_filepath, cloud_filepath
        
        # if multiple vouchers were found, the matching failed
        elif len(found_vouchers) > 1:
            add_to_log("Multiple vouchers found in locally stored files. Coudn't find a clear match.", module_name="Finance", state="error")
            return None, None
        
        # if no voucher was found, the matching failed
        else:
            add_to_log("No voucher found in locally stored files", module_name="Finance", state="error")
            return None, None

    
    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to find voucher in locally stored files", traceback=traceback.format_exc())
        return None, None
    

if __name__ == "__main__":
    transaction = {
    }

    transaction = enrich_transaction_data(transaction)

    # process every pdf file in the same directory as this script and its subdirectories
    # dir_path = os.path.dirname(os.path.realpath(__file__))
    dir_path = "/Users/kitty/Library/CloudStorage/Dropbox/Documents/Finance/Vouchers"
    voucher_filepath_local, voucher_filepath_cloud = search_vouchers_locally(transaction, dir_path)
    print(voucher_filepath_local)
    print(voucher_filepath_cloud)