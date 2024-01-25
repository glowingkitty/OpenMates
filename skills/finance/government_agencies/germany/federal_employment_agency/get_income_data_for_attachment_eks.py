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

from dateutil.relativedelta import relativedelta
from datetime import datetime, timezone
import json
import calendar

from skills.finance.accounting.sevdesk.banking.transaction.get_transactions import get_transactions
from skills.finance.accounting.sevdesk.voucher.get_vouchers import get_vouchers
from skills.finance.accounting.sevdesk.voucher.get_voucher_positions import get_voucher_positions
from skills.finance.accounting.sevdesk.voucher.get_accounting_types import get_accounting_types
from skills.finance.government_agencies.germany.federal_employment_agency.get_keys_for_attachment_eks import get_keys_for_attachment_eks

# get the data for the Attachment for self-employment income (Anlage EKS) for the German Federal Employment Agency (Bundesagentur für Arbeit/Jobcenter)

# https://www.arbeitsagentur.de/datei/anlageeks_ba013054.pdf


def get_income_data_for_attachment_eks(
        start_month: str = None, 
        end_month: str = None,
        save_to_json: bool = True
        ) -> dict:
    try:
        add_to_log(module_name="Federal Employment Agency | Germany | Attachment EKS | Get data", color="yellow", state="start")
        add_to_log("Getting the income data for the 'attachment for self-employment income' (Anlage EKS) ...")

        # if no start_month and end_month are provided, use the current month and year as end_month
        if not start_month and not end_month:
            end_month = datetime.now().strftime("%Y-%m")

        if not start_month and end_month:
            # if only end_month is provided, use the month and year 6 months ago as start_month
            end_month_date = datetime.strptime(end_month, "%Y-%m")
            start_month = (end_month_date - relativedelta(months=5)).strftime("%Y-%m")

        if start_month and not end_month:
            # if only start_month is provided, use the month and year 6 months from now as end_month
            start_month_date = datetime.strptime(start_month, "%Y-%m")
            end_month = (start_month_date + relativedelta(months=5)).strftime("%Y-%m")
        
        # start_month and end_month must be in the format "MM/YYYY"
        # generate all months between start_month and end_month, using datetime
        start_date = datetime.strptime(start_month, "%Y-%m")
        end_date = datetime.strptime(end_month, "%Y-%m")

        months = []
        temp_start_date = start_date
        while temp_start_date <= end_date:
            months.append(temp_start_date.strftime("%Y-%m"))
            temp_start_date += relativedelta(months=1)

        add_to_log(f"Processing the months: {', '.join(months)}", state="success")

        income_data = {"A": {
            "description": "Angaben zu den Betriebseinnahmen"
        }, "B": {
            "description": "Angaben zu den Betriebsausgaben und zum Gewinn"
        }}

        # then get all voucher positions (and use them for the calculation)
        all_voucher_positions = get_voucher_positions()

        # define the accounting types for refunds (incoming money for returned goods and cancelled orders/subscriptions)
        all_accounting_types = get_accounting_types()
        accounting_type_for_refunds = "Erstattungen f\u00fcr Warenr\u00fccksendungen & annullierte Eink\u00e4ufe"

        # get the id of the accounting type for refunds
        accounting_type_for_refunds_id = None
        for accounting_type in all_accounting_types:
            if accounting_type["name"] == accounting_type_for_refunds:
                accounting_type_for_refunds_id = accounting_type["id"]
                break

        # get the voucher data for all months a single time
        voucher_positions_for_all_months = {}
        for month in months:
            voucher_positions_for_all_months[month] = {}
            add_to_log(f"Processing the month: {month}", state="success")

            # get all vouchers which are marked as paid and which have a voucher date between start_month and end_month
            this_month = datetime.strptime(month, "%Y-%m")
            this_month_start_date = this_month.strftime("%Y-%m-%d")
            this_month_last_day = calendar.monthrange(this_month.year, this_month.month)[1]
            this_month_end_date = this_month.replace(day=this_month_last_day).strftime("%Y-%m-%d")

            add_to_log(f"this_month_start_date: {this_month_start_date}", state="success")
            add_to_log(f"this_month_end_date: {this_month_end_date}", state="success")

            # if there are still open transactions for the month, skip the month
            open_transactions = get_transactions(
                is_open=True,
                start_date=this_month_start_date,
                end_date=this_month_end_date
            )
            if open_transactions:
                add_to_log(f"There are still {len(open_transactions)} unprocessed transactions between {this_month_start_date} and {this_month_end_date}. Please add the vouchers for the transactions first, then try again. Skipping the month", state="error")
                voucher_positions_for_all_months[month]["voucher_positions"] = []
                continue
            else:
                add_to_log(f"There are no unprocessed transactions between {this_month_start_date} and {this_month_end_date}.", state="success")
            
            # first get all vouchers
            all_vouchers = get_vouchers(
                status="paid",
                start_date=this_month_start_date,
                end_date=this_month_end_date
            )

            # for every voucher, get the voucher positions
            this_months_voucher_positions = []
            for voucher in all_vouchers:
                voucher_positions = [voucher_position for voucher_position in all_voucher_positions if voucher_position["voucher"]["id"] == voucher["id"]]
                # Add payDate from voucher to each voucher_position
                for position in voucher_positions:
                    position["payDate"] = voucher["payDate"]
                this_months_voucher_positions.extend(voucher_positions)

            voucher_positions_for_all_months[month]["voucher_positions"] = this_months_voucher_positions

            # also get all refunds for that month
            refunds = []
            for voucher_position in this_months_voucher_positions:
                if voucher_position["accountingType"]["id"] == accounting_type_for_refunds_id:
                    refunds.append(voucher_position)

            add_to_log(f"Found {len(refunds)} refunds for the month {month}", state="success")
            voucher_positions_for_all_months[month]["refunds"] = refunds

            add_to_log(f"Successfully retrieved {len(all_vouchers)} vouchers for the month {month}", state="success")

        key_descriptions = get_keys_for_attachment_eks()
        for key, description in key_descriptions.items():
            key_data = {"description": description["description"], "months": {}}


            for month in months:
                # if the category 'Wareneinkauf' is processed, substract the refunds from the amount spend on 'Wareneinkauf'
                if description["description"] == "Wareneinkauf":
                    # get all refunds for that month
                    pass

                
                # calculate the total amount for the accounting types
                total = 0
                found_entries = False
                voucher_links = []

                voucher_positions_for_this_month = voucher_positions_for_all_months[month]["voucher_positions"]


                if voucher_positions_for_this_month:
                    voucher_positions_for_month = [voucher_position for voucher_position in voucher_positions_for_this_month if datetime.strptime(voucher_position["payDate"], '%Y-%m-%dT%H:%M:%S%z').astimezone(timezone.utc).strftime("%Y-%m") == month]
                    if voucher_positions_for_month:
                        for voucher_position in voucher_positions_for_month:
                            # check if any of the accounting types are in the voucher
                            if str(voucher_position["accountingType"]["id"]) in [str(type_id) for type_id in description["accounting_types"]]:
                                # add regardles of debit or credit, to not interfere with the EKS document calculation
                                total += float(voucher_position["sumGross"])
                                voucher_links.append(f"https://my.sevdesk.de/ex/detail/id/{voucher_position['voucher']['id']}")
                                found_entries = True

                # then substract the refunds from the amount spend on 'Wareneinkauf'
                total_before_refunds = total
                if description["description"] == "Wareneinkauf":
                    # get all refunds for that month
                    refunds_for_this_month = voucher_positions_for_all_months[month]["refunds"]
                    if refunds_for_this_month:
                        for refund in refunds_for_this_month:
                            total -= float(refund["sumGross"])
                            voucher_links.append(f"https://my.sevdesk.de/ex/detail/id/{refund['voucher']['id']}")
                            found_entries = True
                                
                if found_entries:
                    if total_before_refunds != total:
                        month_data = {"total": round(total,2), "total_before_refunds": total_before_refunds, "vouchers": voucher_links}
                    else:
                        month_data = {"total": round(total,2), "vouchers": voucher_links}
                    key_data["months"][month] = month_data
                else:
                    key_data["months"][month] = {"total": None, "vouchers": []}

            if key.startswith('A'):
                income_data["A"][key] = key_data
            else:
                income_data["B"][key] = key_data

        # save to json
        if save_to_json:
            filepath = os.path.join(os.path.dirname(__file__), 'income_data.json')
            with open(filepath, 'w') as outfile:
                json.dump(income_data, outfile, indent=4)
            add_to_log(f"Successfully saved the income data to: {filepath}", state="success")


        add_to_log(f"Successfully retrieved the income data", state="success")
        return income_data

    except KeyboardInterrupt:
        shutdown()

    except Exception:
        process_error("Failed to get the income data for the 'attachment for self-employment income' (Anlage EKS)", traceback=traceback.format_exc())
        return None

if __name__ == "__main__":
    get_income_data_for_attachment_eks(start_month="2023-04")