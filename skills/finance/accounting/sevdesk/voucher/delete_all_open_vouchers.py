################

# Default Imports

################
import sys
import os
import re
import requests

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from skills.finance.accounting.sevdesk.voucher.get_vouchers import get_vouchers
from skills.finance.accounting.sevdesk.voucher.delete_voucher import delete_voucher


def delete_all_open_vouchers() -> bool:
    try:
        add_to_log(module_name="SevDesk", color="yellow", state="start")
        add_to_log("Deleting all open vouchers in SevDesk ...")

        # get all open vouchers
        vouchers_draft = get_vouchers(status="draft")
        vouchers_unpaid = get_vouchers(status="unpaid")

        # delete all open vouchers
        vouchers = vouchers_draft + vouchers_unpaid
        total_deleted = 0
        add_to_log(f"Deleting {len(vouchers)} vouchers ...")
        for voucher in vouchers:
            success = delete_voucher(voucher_id=voucher["id"])
            if not success:
                add_to_log(f"Failed to delete voucher with ID {voucher['id']}.", state="error")
            else:
                total_deleted += 1
                add_to_log(f"Deleted voucher {total_deleted}/{len(vouchers)} with ID {voucher['id']}.", state="success")

        add_to_log(f"Successfully deleted {total_deleted} vouchers.", state="success")
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception as e:
        process_error(f"Failed to delete all vouchers", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    delete_all_open_vouchers()