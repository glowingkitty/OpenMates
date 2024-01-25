################

# Default Imports

################
import sys
import os
import re
import traceback
from forex_python.converter import CurrencyRates, CurrencyCodes

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('skills.*', '', full_current_path)
sys.path.append(main_directory)
from server import *

################

from datetime import datetime

def get_currency_conversion(input_currency_name: str, input_currency_value: float, output_currency_name: str, date: str) -> float:
    try:
        add_to_log(module_name="Currency Exchange", color="yellow", state="start")
        add_to_log("Converting currency ...")
        
        c = CurrencyRates()
        date_obj = datetime.strptime(date, '%Y-%m-%d')  # convert string to datetime
        conversion_rate = c.get_rate(input_currency_name, output_currency_name, date_obj)
        converted_value = round(conversion_rate * input_currency_value,2)
        
        add_to_log(f"Successfully converted {input_currency_value} {input_currency_name} to {converted_value} {output_currency_name} using rate from {date}", state="success")
        return converted_value
    
    except KeyboardInterrupt:
        shutdown()
    
    except Exception:
        process_error(f"Failed to convert currency from '{input_currency_name}' to '{output_currency_name}' on '{date}'", traceback=traceback.format_exc())
        return None
    
if __name__ == "__main__":
    # Example usage:
    converted_amount = get_currency_conversion(
        input_currency_name="USD", 
        input_currency_value=25.43, 
        output_currency_name="EUR", 
        date="2023-12-08"
    )
    print(f"Converted amount: {converted_amount} EUR")