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

from server import *
################

import requests
from server.api.models.skills.finance.skills_finance_get_transactions import FinanceGetTransactionsInput,FinanceGetTransactionsOutput, Transaction


async def get_transactions(
        bank_api_token: str,
        from_date: str,
        to_date: str,
        account: str,
        count: int,
        type: str = None,
        bank: str = "Revolut Business"
    ) -> FinanceGetTransactionsOutput:
    input_data = FinanceGetTransactionsInput(
        from_date=from_date,
        to_date=to_date,
        bank=bank,
        account=account,
        count=count,
        type=type
    )

    url = "https://b2b.revolut.com/api/1.0/transactions"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {bank_api_token}'
    }
    params = {
        'from': input_data.from_date,
        'to': input_data.to_date,
        'count': input_data.count,
        'account': input_data.account
    }
    if type:
        params['type'] = type

    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()

    transactions_data = response.json()
    transactions = [Transaction(**transaction) for transaction in transactions_data]

    return FinanceGetTransactionsOutput(transactions=transactions)