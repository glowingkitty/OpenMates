import pytest
from server.api.endpoints.skills.akaunting.helper.create_bill import create_bill
from server.api.endpoints.skills.akaunting.helper.delete_bill import delete_bill
from server.api.models.skills.akaunting.skills_akaunting_create_expense import BillInfo
from server.api.models.skills.akaunting.helper.skills_akaunting_create_item import ItemInfo
from server.api.models.skills.akaunting.skills_akaunting_create_income import CategoryInfo, SubCategoryInfo

@pytest.mark.asyncio
async def test_create_and_delete_bills():
    test_bills = [
        BillInfo(
            date="2023-04-15",
            due_date="2023-05-15",
            items=[
                ItemInfo(
                    name="Widget",
                    quantity=1,
                    net_price=10.00
                )
            ],
            currency="USD",
            category=CategoryInfo(name="Purchase"),
            sub_category=SubCategoryInfo(name="Raw Materials")
        ),
        BillInfo(
            date="2023-04-16",
            due_date="2023-05-16",
            items=[
                ItemInfo(
                    name="Gadget",
                    quantity=2,
                    net_price=15.50
                ),
                ItemInfo(
                    name="Gizmo",
                    quantity=3,
                    net_price=5.75
                )
            ],
            currency="EUR",
            category=CategoryInfo(name="Purchase"),
            sub_category=SubCategoryInfo(name="Finished Goods")
        )
    ]

    for bill in test_bills:
        # Create bill
        created_bill = await create_bill(bill)

        # Assert that the bill was created successfully
        assert created_bill.bill.id is not None
        assert created_bill.bill.date == bill.date
        assert created_bill.bill.due_date == bill.due_date
        assert created_bill.bill.currency == bill.currency
        assert len(created_bill.bill.items) == len(bill.items)
        assert created_bill.bill.category.name == bill.category.name
        assert created_bill.bill.sub_category.name == bill.sub_category.name

        # Delete bill
        delete_result = await delete_bill(created_bill.bill.id)

        # Assert that the bill was deleted successfully
        assert delete_result['success'] is True
        assert f"Bill with ID {created_bill.bill.id} has been successfully deleted." in delete_result['message']

@pytest.mark.asyncio
async def test_delete_nonexistent_bill():
    # Try to delete a bill with a non-existent ID
    non_existent_id = 99999
    delete_result = await delete_bill(non_existent_id)

    # Assert that the deletion failed as expected
    assert delete_result['success'] is False
    assert f"No bill found with ID {non_existent_id}." in delete_result['message']