import pytest
from server.api.endpoints.skills.akaunting.helper.get_or_create_bank_account import get_or_create_bank_account
from server.api.endpoints.skills.akaunting.helper.delete_bank_account import delete_bank_account
from server.api.models.skills.akaunting.helper.skills_akaunting_create_bank_account import BankAccountInfo

@pytest.mark.asyncio
async def test_create_and_delete_bank_accounts():
    test_accounts = [
        BankAccountInfo(
            account_name="Global Tech Solutions Bank",
            account_number="1234567890",
            currency_code="USD",
            opening_balance=10000,
            bank_name="Chase Bank",
            bank_phone="+16505550123",
            bank_address="123 Main St, New York, NY 10001"
        ),
        BankAccountInfo(
            account_name="Berlin Engineering Konto",
            account_number="DE89370400440532013000",
            currency_code="EUR",
            opening_balance=15000,
            bank_name="Deutsche Bank"
        ),
        BankAccountInfo(
            account_name="Sydney Green Energy Account",
            account_number="062-000 12345678",
            currency_code="AUD",
            opening_balance=20000
        ),
        BankAccountInfo(
            account_name="東京エレクトロニクス銀行",
            account_number="1234567",
            currency_code="JPY",
            opening_balance=1000000,
            bank_name="みずほ銀行",
            bank_address="〒100-8176 東京都千代田区大手町1-5-5"
        ),
        BankAccountInfo(
            account_name="Compte Fournitures Locales",
            account_number="FR1420041010050500013M02606",
            currency_code="EUR",
            opening_balance=8000,
            bank_name="BNP Paribas"
        ),
        BankAccountInfo(
            account_name="Cчет ООО 'Русские Технологии'",
            account_number="40702810400000123456",
            currency_code="RUB",
            opening_balance=500000,
            bank_name="Сбербанк"
        ),
        BankAccountInfo(
            account_name="中国科技有限公司账户",
            account_number="6225880123456789",
            currency_code="CNY",
            opening_balance=100000
        ),
        BankAccountInfo(
            account_name="Nairobi Tech Innovations Account",
            account_number="1234567890123",
            currency_code="USD",
            opening_balance=1000000,
            bank_name="Equity Bank"
        ),
        BankAccountInfo(
            account_name="Conta Inovações Brasileiras",
            account_number="00000000-0",
            currency_code="USD",
            opening_balance=50000,
            bank_name="Banco do Brasil"
        )
    ]

    for account in test_accounts:
        # Create bank account
        created_account = get_or_create_bank_account(account)

        # Assert that the bank account was created successfully
        assert created_account.id is not None
        assert created_account.account_name == account.account_name
        assert created_account.account_number == account.account_number
        assert created_account.currency_code == account.currency_code
        assert created_account.opening_balance == account.opening_balance
        if account.bank_name:
            assert created_account.bank_name == account.bank_name
        if account.bank_phone:
            assert created_account.bank_phone == account.bank_phone
        if account.bank_address:
            assert created_account.bank_address == account.bank_address

        # Delete bank account
        delete_result = await delete_bank_account(created_account.id)

        # Assert that the bank account was deleted successfully
        assert delete_result['success'] is True
        assert f"Bank account with ID {created_account.id} has been successfully deleted." in delete_result['message']

@pytest.mark.asyncio
async def test_delete_nonexistent_bank_account():
    # Try to delete a bank account with a non-existent ID
    non_existent_id = 99999
    delete_result = await delete_bank_account(non_existent_id)

    # Assert that the deletion failed as expected
    assert delete_result['success'] is False
    assert f"No bank account found with ID {non_existent_id}." in delete_result['message']