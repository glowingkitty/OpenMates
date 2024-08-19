import requests
from datetime import datetime
from server.api.models.skills.revolut_business.skills_revolut_business_get_transactions import RevolutBusinessGetTransactionsOutput, Transaction

async def get_transactions(
        token: str,
        from_date: str,
        to_date: str,
        account: str,
        count: int,
        type: str = None
    ) -> RevolutBusinessGetTransactionsOutput:
    url = "https://b2b.revolut.com/api/1.0/transactions"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    params = {
        'from': from_date,
        'to': to_date,
        'count': count,
        'account': account
    }
    if type:
        params['type'] = type

    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()

    transactions_data = response.json()
    transactions = [Transaction(**transaction) for transaction in transactions_data]

    return RevolutBusinessGetTransactionsOutput(transactions=transactions)