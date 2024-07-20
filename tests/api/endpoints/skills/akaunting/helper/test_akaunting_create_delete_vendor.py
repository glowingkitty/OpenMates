import pytest
from server.api.endpoints.skills.akaunting.helper.create_vendor import create_vendor
from server.api.endpoints.skills.akaunting.helper.delete_vendor import delete_vendor
from server.api.models.skills.akaunting.helper.skills_akaunting_create_vendor import VendorInfo

@pytest.mark.asyncio
async def test_create_and_delete_vendors():
    test_vendors = [
        VendorInfo(
            name="Global Tech Solutions Inc.",
            email="info@globaltechsolutions.com",
            tax_number="98-7654321",
            currency_code="USD",
            phone="+16505550123",
            website="https://www.globaltechsolutions.com",
            address="1 Infinite Loop",
            city="Cupertino",
            zip_code="95014",
            state="CA",
            country="US",
            reference="GTS-2023-001"
        ),
        VendorInfo(
            name="Berlin Precision Engineering GmbH",
            email="kontakt@berlinengineering.de",
            tax_number="DE123456789",
            currency_code="EUR",
            phone="+493012345678",
            website="https://www.berlinengineering.de",
            address="Unter den Linden 10",
            city="Berlin",
            zip_code="10117",
            state="Berlin",
            country="DE"
        ),
        VendorInfo(
            name="Sydney Green Energy Pty Ltd",
            email="info@sydneygreenenergy.com.au",
            currency_code="AUD",
            phone="+61298765432",
            country="AU"
        ),
        VendorInfo(
            name="Tokyo Electronics Co., Ltd.",
            tax_number="T1234567890",
            currency_code="JPY",
            address="1-1-1 Akihabara",
            city="Tokyo",
            country="JP"
        ),
        VendorInfo(
            name="Local Supplies Ltd",
            email="contact@localsupplies.co.uk",
            currency_code="GBP"
        ),
        VendorInfo(
            name="株式会社山田電機",
            email="info@yamada-denki.co.jp",
            tax_number="T9876543210",
            currency_code="JPY",
            phone="+81345678901",
            website="https://www.yamada-denki.co.jp",
            address="東京都千代田区丸の内1-1-1",
            city="東京",
            zip_code="100-0005",
            country="JP"
        ),
        VendorInfo(
            name="上海龙腾科技有限公司",
            email="contact@longtechshanghai.cn",
            tax_number="310000400000000",
            currency_code="CNY",
            phone="+862161234567",
            website="http://www.longtechshanghai.cn",
            address="上海市浦东新区张江高科技园区",
            city="上海",
            zip_code="201203",
            country="CN"
        ),
        VendorInfo(
            name="Müller & Söhne GmbH",
            email="info@mueller-soehne.de",
            tax_number="DE987654321",
            currency_code="EUR",
            phone="+4989123456",
            website="https://www.mueller-soehne.de",
            address="Hauptstraße 1",
            city="München",
            zip_code="80331",
            state="Bayern",
            country="DE"
        ),
        VendorInfo(
            name="Société Générale d'Électronique",
            email="contact@sge-electronique.fr",
            tax_number="FR12345678900",
            currency_code="EUR",
            phone="+33123456789",
            website="https://www.sge-electronique.fr",
            address="15 Rue de la République",
            city="Lyon",
            zip_code="69001",
            country="FR"
        ),
        VendorInfo(
            name="ООО 'Русские Технологии'",
            email="info@rustech.ru",
            tax_number="7701234567",
            currency_code="RUB",
            phone="+74951234567",
            website="https://www.rustech.ru",
            address="ул. Тверская, 1",
            city="Москва",
            zip_code="125009",
            country="RU"
        )
    ]

    for vendor in test_vendors:
        # Create vendor
        created_vendor = await create_vendor(vendor)

        # Assert that the vendor was created successfully
        assert created_vendor.id is not None
        assert created_vendor.name == vendor.name
        assert created_vendor.email == vendor.email
        assert created_vendor.tax_number == vendor.tax_number
        assert created_vendor.currency_code == vendor.currency_code
        assert created_vendor.phone == vendor.phone
        assert created_vendor.website == vendor.website
        assert created_vendor.address == vendor.address
        assert created_vendor.city == vendor.city
        assert created_vendor.zip_code == vendor.zip_code
        assert created_vendor.state == vendor.state
        assert created_vendor.country == vendor.country

        # Delete vendor
        delete_result = await delete_vendor(created_vendor.id)

        # Assert that the vendor was deleted successfully
        assert delete_result['success'] is True
        assert f"Vendor with ID {created_vendor.id} has been successfully deleted." in delete_result['message']

@pytest.mark.asyncio
async def test_delete_nonexistent_vendor():
    # Try to delete a vendor with a non-existent ID
    non_existent_id = 99999
    delete_result = await delete_vendor(non_existent_id)

    # Assert that the deletion failed as expected
    assert delete_result['success'] is False
    assert f"No vendor found with ID {non_existent_id}." in delete_result['message']