# General software development guidelines (always follow these when writing or improving code)
- make sure the code is easy to understand, reliable, and easy to maintain
- if no specific programming language is requested, use python 3.10
- keep the code organized, add comments to explain the code, use descriptive variable names
- make sure secrets are not hardcoded in the code


# Python software development guidelines (always follow these when writing or improving python code)
- use os.path.join to join filepaths
- use "add_to_log()" instead of "print()" to print to the console and log file
- make sure no imports are missing
- do not use classes. Use functions only (except when specificly asked to use classes)
- have one function per file if possible
- use descriptive function names, folder names, file names
- always include a test of the function at the end of the file


# Templates for python files
The following code is a good and fully working template for a python file for 'OpenMates':
```/large_language_models/count_tokens.py```:
```python
{ guidelines/template.py }
```
And for better context, the init file for the functions folder:
```/server/__init__.py```:
```python
import traceback
import sys
import os
import re

# Fix import path
full_current_init_path = os.path.realpath(__file__)
main_directory_for_init = re.sub('skills.*', '', full_current_init_path)
sys.path.append(main_directory_for_init)

from server.setup.load_secrets import load_secrets
from server.setup.load_config import load_config
from server.setup.load_bots import load_bots
from server.setup.load_profile_details import load_profile_details
from server.error.process_error import process_error
from server.logging.add_to_log import add_to_log
from server.shutdown.shutdown import shutdown
```

Whenever an API will create costs, implement a warning and option to cancel, like this:
```python
add_to_log(
    message=f"You are about to spend {round(costs['total_costs'],4)} {costs['currency']} for converting the text to speech.",
    line_number=inspect.currentframe().f_lineno,
    file_name=os.path.basename(__file__)
    )

if config["environment"] == "development":
    add_to_log(
        message=f"Press CTRL+C to cancel or wait 5 seconds to auto continue ..."
        line_number=inspect.currentframe().f_lineno,
        file_name=os.path.basename(__file__))
    time.sleep(5)
```