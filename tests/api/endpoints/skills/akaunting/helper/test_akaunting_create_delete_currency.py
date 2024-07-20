import pytest
from server.api.endpoints.skills.akaunting.helper.get_or_create_currency import get_or_create_currency
from server.api.endpoints.skills.akaunting.helper.delete_currency import delete_currency
from server.api.models.skills.akaunting.helper.skills_akaunting_create_currency import CurrencyInfo

@pytest.mark.asyncio
async def test_create_and_delete_currencies():
    test_currencies = [
        CurrencyInfo(
            name="Canadian Dollar",
            code="CAD",
            rate=1.25,
            precision=2,
            symbol="C$",
            symbol_first=1,
            decimal_mark=".",
            thousands_separator=",",
            enabled=1
        ),
        CurrencyInfo(
            name="Australian Dollar",
            code="AUD",
            rate=1.32,
            precision=2,
            symbol="A$",
            symbol_first=1,
            decimal_mark=".",
            thousands_separator=",",
            enabled=1
        ),
        CurrencyInfo(
            name="Japanese Yen",
            code="JPY",
            rate=110,
            precision=0,
            symbol="¥",
            symbol_first=1,
            decimal_mark=".",
            thousands_separator=",",
            enabled=1
        ),
        CurrencyInfo(
            name="British Pound",
            code="GBP",
            rate=0.73,
            precision=2,
            symbol="£",
            symbol_first=1,
            decimal_mark=".",
            thousands_separator=",",
            enabled=1
        ),
        CurrencyInfo(
            name="Swiss Franc",
            code="CHF",
            rate=0.92,
            precision=2,
            symbol="Fr.",
            symbol_first=0,
            decimal_mark=".",
            thousands_separator="'",
            enabled=1
        )
    ]

    for currency in test_currencies:
        # Create currency
        created_currency = get_or_create_currency(currency)

        # Assert that the currency was created successfully
        assert created_currency.id is not None
        assert created_currency.name == currency.name
        assert created_currency.code == currency.code
        assert created_currency.rate == currency.rate
        assert created_currency.precision == currency.precision
        assert created_currency.symbol == currency.symbol
        assert created_currency.symbol_first == currency.symbol_first
        assert created_currency.decimal_mark == currency.decimal_mark
        assert created_currency.thousands_separator == currency.thousands_separator
        assert created_currency.enabled == currency.enabled

        # Delete currency
        delete_result = await delete_currency(created_currency.id)

        # Assert that the currency was deleted successfully
        assert delete_result['success'] is True
        assert f"Currency with ID {created_currency.id} has been successfully deleted." in delete_result['message']

@pytest.mark.asyncio
async def test_delete_nonexistent_currency():
    # Try to delete a currency with a non-existent ID
    non_existent_id = 99999
    delete_result = await delete_currency(non_existent_id)

    # Assert that the deletion failed as expected
    assert delete_result['success'] is False
    assert f"No currency found with ID {non_existent_id}." in delete_result['message']