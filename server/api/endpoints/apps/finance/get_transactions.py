from server.api.models.apps.finance.skills_finance_get_transactions import FinanceGetTransactionsInput,FinanceGetTransactionsOutput, Transaction
from server.api.endpoints.apps.finance.providers.revolut_business.get_transactions import get_transactions as get_transactions_revolut_business


async def get_transactions(
        bank_api_token: str,
        from_date: str,
        to_date: str,
        bank: str,
        account: str,
        count: int,
        type: str = None
    ) -> FinanceGetTransactionsOutput:
    input_data = FinanceGetTransactionsInput(
        from_date=from_date,
        to_date=to_date,
        bank=bank,
        account=account,
        count=count,
        type=type
    )

    if input_data.bank == "Revolut Business":
        return await get_transactions_revolut_business(
            bank_api_token=bank_api_token,
            from_date=input_data.from_date,
            to_date=input_data.to_date,
            bank=input_data.bank,
            account=input_data.account,
            count=input_data.count,
            type=input_data.type
        )