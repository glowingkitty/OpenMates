################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server.api import *
################


from server.api.models.skills.akaunting.skills_akaunting_create_expense import AkauntingCreateExpenseOutput
from typing import Dict, List


async def create_expense(token: str, vendor: Dict, items: List[Dict]) -> AkauntingCreateExpenseOutput:
    """Create a new expense in Akaunting"""
    # TODO: Implement the actual logic to create a expense in Akaunting
    # This should include:
    # 1. Creating a vendor if it doesn't exist
    # 2. Creating a bill
    # 3. Creating a transaction
    # 4. Linking everything together

    # For now, we'll just return a dummy response
    return AkauntingCreateExpenseOutput(
        success=True,
        purchase_id=12345
    )